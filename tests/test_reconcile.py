"""Repeat-run behaviour: identity, new/missing/removed/reopened/reposted."""
import pytest

from app import db
from app.reconcile import apply_result, normalize_url, role_key, update_agency

AT = ["2026-11-0%dT06:00:00+00:00" % d for d in range(1, 10)]


@pytest.fixture()
def conn(tmp_path):
    db.init(tmp_path / "t.db")
    c = db.connect(tmp_path / "t.db")
    c.execute("INSERT INTO agencies (id, handle, name, website, created_at) VALUES (1,'acme','Acme','https://acme.com/',?)",
              (AT[0],))
    yield c
    c.close()


def run(conn, n, status, jobs, careers_hash="h1"):
    agency = dict(conn.execute("SELECT * FROM agencies WHERE id=1").fetchone())
    res = {"status": status, "careers_url": "https://acme.com/careers", "careers_hash": careers_hash,
           "partner": {"website": "https://acme.com/"}, "jobs": jobs}
    ch = apply_result(conn, run_id=n, agency=agency, result=res, at=AT[n])
    update_agency(conn, run_id=n, agency=agency, result=res, at=AT[n])
    return ch


def roles(conn):
    return {r["title"]: dict(r) for r in conn.execute("SELECT * FROM roles")}


DEV = {"title": "Shopify Developer", "url": "https://boards.greenhouse.io/acme/jobs/1?gh_src=x"}
PM = {"title": "Project Manager", "url": "https://boards.greenhouse.io/acme/jobs/2"}


def test_url_normalisation_and_keys():
    assert normalize_url("https://www.Acme.com/careers/dev/?utm_source=x#top") == "https://acme.com/careers/dev"
    # A role whose "url" is just the careers page is keyed by title + location instead.
    k = role_key("acme", {"title": "Sr. Developer", "url": "https://acme.com/careers/", "location": "Remote"},
                 "https://acme.com/careers")
    assert k == "t:acme:senior developer:remote"


def test_same_links_keep_identity_and_user_data(conn):
    ch = run(conn, 1, "roles_found", [DEV, PM])
    assert len(ch.added) == 2
    dev_id = roles(conn)["Shopify Developer"]["id"]
    conn.execute("INSERT INTO users (id,email,name,password_hash,created_at) VALUES (1,'a@b.c','A','x',?)", (AT[0],))
    conn.execute("INSERT INTO user_roles VALUES (1, ?, 'applied', 'note', ?)", (dev_id, AT[1]))

    ch = run(conn, 2, "roles_found", [dict(DEV, url=DEV["url"].replace("gh_src=x", "gh_src=y")), PM])
    assert ch.added == [] and ch.removed == 0
    r = roles(conn)["Shopify Developer"]
    assert r["id"] == dev_id and r["first_seen_run"] == 1 and r["last_seen_at"] == AT[2]
    assert conn.execute("SELECT status FROM user_roles WHERE role_id=?", (dev_id,)).fetchone()[0] == "applied"


def test_removed_only_after_two_successful_misses(conn):
    run(conn, 1, "roles_found", [DEV, PM])
    run(conn, 2, "rate_limited", [])                    # failed check: nothing changes
    assert roles(conn)["Project Manager"]["state"] == "open"
    run(conn, 3, "roles_found", [DEV])                  # first miss
    assert roles(conn)["Project Manager"]["state"] == "missing"
    run(conn, 4, "site_unreachable", [])                # failed check doesn't count
    assert roles(conn)["Project Manager"]["state"] == "missing"
    ch = run(conn, 5, "roles_found", [DEV])             # second successful miss
    assert ch.removed == 1 and roles(conn)["Project Manager"]["state"] == "closed"


def test_missing_role_that_returns_is_not_new(conn):
    run(conn, 1, "roles_found", [DEV, PM])
    run(conn, 2, "roles_found", [DEV])
    ch = run(conn, 3, "roles_found", [DEV, PM])
    assert ch.added == [] and roles(conn)["Project Manager"]["state"] == "open"


def test_closed_role_reopens(conn):
    run(conn, 1, "roles_found", [DEV, PM])
    run(conn, 2, "careers_page_no_openings", [])
    run(conn, 3, "careers_page_no_openings", [])
    assert roles(conn)["Shopify Developer"]["state"] == "closed"
    ch = run(conn, 4, "roles_found", [DEV])
    assert ch.added == [] and [x["title"] for x in ch.reopened] == ["Shopify Developer"]


def test_repost_with_new_link_is_same_role(conn):
    run(conn, 1, "roles_found", [DEV, PM])
    dev_id = roles(conn)["Shopify Developer"]["id"]
    ch = run(conn, 2, "roles_found", [dict(DEV, url="https://boards.greenhouse.io/acme/jobs/99"), PM])
    assert ch.added == []
    r = roles(conn)["Shopify Developer"]
    assert r["id"] == dev_id and r["url"].endswith("/99")
    assert conn.execute("SELECT COUNT(*) FROM role_events WHERE type='reposted'").fetchone()[0] == 1


def test_two_open_roles_with_same_title_stay_separate(conn):
    a = {"title": "Solutions Architect", "url": "https://x.io/jobs/1", "location": "Colombia"}
    b = {"title": "Solutions Architect", "url": "https://x.io/jobs/2", "location": "Colombia"}
    run(conn, 1, "roles_found", [a, b])
    ch = run(conn, 2, "roles_found", [a, b])
    assert ch.added == [] and conn.execute("SELECT COUNT(*) FROM roles WHERE state='open'").fetchone()[0] == 2


def test_duplicate_links_in_one_run_stored_once(conn):
    ch = run(conn, 1, "roles_found", [DEV, dict(DEV), dict(DEV, url=DEV["url"] + "&utm_source=li")])
    assert len(ch.added) == 1


def test_changed_careers_page_reopens_review(conn):
    run(conn, 1, "careers_page_roles_unclear", [], careers_hash="h1")
    conn.execute("UPDATE agencies SET review_state='no_openings', review_hash='h1' WHERE id=1")
    run(conn, 2, "careers_page_roles_unclear", [], careers_hash="h1")
    assert conn.execute("SELECT review_state FROM agencies").fetchone()[0] == "no_openings"
    run(conn, 3, "careers_page_roles_unclear", [], careers_hash="h2")
    assert conn.execute("SELECT review_state FROM agencies").fetchone()[0] is None
