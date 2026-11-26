"""Offline tests for the heuristics (cases taken from real partner sites)."""
from scraper.ats import detect_ats
from scraper.careers import STRONG_TEXT, is_non_company_site, score_link
from scraper.extract import extract_jobs, looks_like_title

HOME = "https://agency.com/"


def test_title_heuristic():
    for good in ["Creative Director", "UX/UI Designer", "AI Enablement Lead", "Senior Shopify Developer (Remote)",
                 "Head of Growth", "Engineer"]:
        assert looks_like_title(good), good
    for bad in ["Ask Avenue Z's AI assistant", "Meet our Creative Director", "Internship Opportunities",
                "Submit your resume and we will be in touch.", "We hire operators."]:
        assert not looks_like_title(bad), bad


def test_careers_link_text():
    assert STRONG_TEXT.match("Careers →") and STRONG_TEXT.match("Join our team") and STRONG_TEXT.match("We're hiring!")
    assert not STRONG_TEXT.match("Hiring a Shopify Expert")


def test_score_link():
    assert score_link("https://agency.com/careers", "Careers", HOME) == 90
    assert score_link("https://agency.com/pages/p3-careers", "Work here", HOME) == 70
    assert score_link("https://agency.com/culture", "Careers", HOME) == 60
    assert score_link("https://agency.com/blog/we-are-hiring", "We're hiring", HOME) == 0
    assert score_link("https://jobs.lever.co/agency", "x", HOME) == 100
    assert score_link("https://other.com/careers", "Careers", HOME) == 0
    # Merchant-facing "hire us" pages are not careers pages.
    assert score_link("https://agency.com/hiring-a-shopify-expert-in-the-usa", "x", HOME) == 0
    assert score_link("https://agency.com/shopify-plus-expert-hiring-checklist", "x", HOME) == 0
    assert score_link("https://agency.com/contact", "Work with us", HOME) == 0
    assert score_link("https://agency.com/hiring", "We're hiring", HOME) == 90
    assert score_link("https://agency.com/careers-at-acme", "x", HOME) == 70


def test_non_company_sites():
    for u in ["https://www.instagram.com/x/", "https://calendly.com/x", "https://www.upwork.com/freelancers/x"]:
        assert is_non_company_site(u)
    assert not is_non_company_site("https://www.darkroomagency.com/")


def test_detect_ats():
    html = ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
            '<a href="https://jobs.lever.co/foo/123">x</a><a href="https://www.workable.com">powered by</a>'
            "var u='https://boards-api.greenhouse.io/v1/boards/bevelpr/jobs';")
    assert detect_ats(html) == [("greenhouse", "acme"), ("greenhouse", "bevelpr"), ("lever", "foo")]


def test_section_roles_and_no_openings():
    page = """<html><body><nav><a>Shopify Developer services</a></nav>
      <h2>Current Openings</h2><div><div>Creative</div><div>Senior Digital Designer</div></div>
      <h2>Perks</h2><h3>Internship Opportunities</h3></body></html>"""
    jobs, no_open, _ = extract_jobs(page, HOME + "careers")
    assert [j.title for j in jobs] == ["Senior Digital Designer"] and not no_open

    empty = "<html><body><h2>Teams</h2><h3>Growth Marketing</h3><h2>nothing open right now.</h2></body></html>"
    jobs, no_open, _ = extract_jobs(empty, HOME + "careers")
    assert jobs == [] and no_open


def test_card_links_split_title_and_location():
    page = """<h2>Open positions</h2>
      <a href="https://agency.com/careers/account-executive"><h3>Account Executive</h3>
        <span>Remote (Chicago, IL HQ)</span><span>Full time</span></a>
      <a href="https://agency.com/careers/marketing-intern"><div>Marketing</div><div>Marketing Intern</div>
        <p>Hybrid, Birmingham metro · Part-time internship · $16 to $19 per hour</p></a>
      <div>data-architect-july-2026</div>"""
    jobs, _, _ = extract_jobs(page, HOME + "careers")
    assert [(j.title, j.location) for j in jobs] == [
        ("Account Executive", "Remote (Chicago, IL HQ)"),
        ("Marketing Intern", "Hybrid, Birmingham metro · Part-time internship · $16 to $19 per hour"),
    ]


def test_jsonld():
    page = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
      "title":"Shopify Developer","jobLocation":{"address":{"addressLocality":"Austin","addressRegion":"TX"}}}</script>"""
    jobs, _, _ = extract_jobs(page, HOME + "careers")
    assert jobs[0].title == "Shopify Developer" and jobs[0].location == "Austin, TX" and jobs[0].confidence == "high"
