"""Admin commands.

    python manage.py init-db
    python manage.py create-user you@example.com "Your Name" --admin
    python manage.py reset-password you@example.com
    python manage.py serve                     # http://127.0.0.1:8000 (HOST/PORT from .env)
    python manage.py import-cache output/cache/store_building_US   # load results from the CLI scraper
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from app import auth, db, settings


def _password(prompt="Password (10+ characters): ") -> str:
    pw = getpass.getpass(prompt)
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match.")
    return pw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    cu = sub.add_parser("create-user")
    cu.add_argument("email")
    cu.add_argument("name")
    cu.add_argument("--admin", action="store_true")
    rp = sub.add_parser("reset-password")
    rp.add_argument("email")
    sub.add_parser("serve")
    ic = sub.add_parser("import-cache", help="import per-agency JSON results written by scrape.py")
    ic.add_argument("folder")
    args = ap.parse_args()

    db.init()
    conn = db.connect()
    if args.cmd == "init-db":
        print(f"Database ready: {settings.DB_PATH}")
    elif args.cmd == "create-user":
        try:
            auth.create_user(conn, args.email, args.name, _password(), args.admin)
        except ValueError as e:
            sys.exit(str(e))
        print(f"Created {'admin ' if args.admin else ''}user {args.email}")
    elif args.cmd == "reset-password":
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (args.email,)).fetchone():
            sys.exit("No such user.")
        pw = _password("New password: ")
        if len(pw) < 10:
            sys.exit("Password must be at least 10 characters.")
        with db.tx(conn):
            conn.execute("UPDATE users SET password_hash=? WHERE email=?", (auth.hash_password(pw), args.email))
            conn.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)", (args.email,))
        print("Password updated.")
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, proxy_headers=True)
    elif args.cmd == "import-cache":
        import_cache(conn, Path(args.folder))


def import_cache(conn, folder: Path) -> None:
    """Load a finished `scrape.py` run as a (baseline) run, so the board isn't empty on day one."""
    from app.reconcile import apply_result, update_agency
    files = sorted(folder.glob("*.json"))
    if not files:
        sys.exit(f"No JSON files in {folder}")
    at = db.now()
    with db.tx(conn):
        baseline = conn.execute("SELECT COUNT(*) FROM runs WHERE status='completed'").fetchone()[0] == 0
        run_id = conn.execute("INSERT INTO runs (trigger, status, baseline, started_at, total, processed, settings)"
                              " VALUES ('import','running',?,?,?,?,?)",
                              (int(baseline), at, len(files), len(files), json.dumps({"source": str(folder)}))).lastrowid
        counts: dict[str, int] = {}
        for f in files:
            r = json.loads(f.read_text(encoding="utf-8"))
            p = r["partner"]
            conn.execute("INSERT INTO agencies (handle, name, partner_id, profile_url, created_at) VALUES (?,?,?,?,?)"
                         " ON CONFLICT(handle) DO NOTHING", (p["handle"], p["name"], p.get("partner_id"),
                                                             p.get("profile_url"), at))
            agency = dict(conn.execute("SELECT * FROM agencies WHERE handle=?", (p["handle"],)).fetchone())
            apply_result(conn, run_id=run_id, agency=agency, result=r, at=at)
            update_agency(conn, run_id=run_id, agency=agency, result=r, at=at)
            conn.execute("INSERT OR REPLACE INTO run_agencies VALUES (?,?,?,?,?,?)",
                         (run_id, agency["id"], r["status"], len(r["jobs"]), r.get("notes", ""), at))
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        conn.execute("UPDATE runs SET status='completed', finished_at=?, status_counts=?, hiring=?, roles_found=?,"
                     " new_roles=(SELECT COUNT(*) FROM role_events WHERE run_id=? AND type='added') WHERE id=?",
                     (db.now(), json.dumps(counts), q("SELECT COUNT(DISTINCT agency_id) FROM roles WHERE state!='closed'"),
                      q("SELECT COUNT(*) FROM roles WHERE state!='closed'"), run_id, run_id))
    print(f"Imported {len(files)} agencies as run #{run_id}" + (" (baseline)" if baseline else ""))


if __name__ == "__main__":
    main()
