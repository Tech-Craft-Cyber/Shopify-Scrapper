# Agency Roles

A team job board built from the Shopify Partner Directory. It scrapes every agency in a directory
category (default: [Store building, US](https://www.shopify.com/partners/directory/services/store_building?location=US)),
finds each agency's careers page, extracts the open roles, and keeps them up to date on a schedule.

- **Backend:** FastAPI + SQLite (`app/`), scraper in `scraper/`
- **Frontend:** React + TypeScript, built with Vite (`web/`)
- **Design mockups:** `design/` (`python design/render.py` regenerates the PNGs)

## Quick start (local)

```bash
pip install -r requirements.txt
python -m playwright install chromium          # headless-browser fallback for JS-heavy sites

cd web && npm install && npm run build && cd ..   # builds web/dist, served by FastAPI

python manage.py init-db
python manage.py create-user you@example.com "Your Name" --admin
python manage.py serve                          # http://127.0.0.1:8000
```

Sign in, open **Runs**, then press **Run now** or turn on the schedule. A full run of ~919 agencies takes
about an hour.

To work on the frontend with hot reload, run `python manage.py serve` in one terminal and `cd web && npm run dev`
in another, then open http://localhost:5173. Vite proxies `/api` to port 8000.

## Pages

| Page | What it does |
|---|---|
| **Roles** | All open roles with filters (role type, remote/hybrid/on-site, source, tier, team size, new, saved). The detail panel has your status (Saved / Applied / Not interested), private notes, team activity, and agency facts. Teammates see your status but not your notes. |
| **Agencies** | Every agency in the directory, grouped by result: Hiring, No openings, **Needs review**, No careers page, Other. **Watch** an agency to get an alert when it posts a role. The *Needs review* tab lists careers pages the scraper couldn't read: open the page, then mark *No openings*, *Add role* by hand, or *Not relevant*. |
| **Runs** | Schedule (every N hours / daily on chosen days / cron, in your time zone), live progress and log, run history, and summary charts. Only admins can change the schedule or start/stop runs. |
| Account menu | Change password, export roles as CSV. Admins also manage the team here. |

## How repeat runs are handled

Every run checks every agency again and merges the result into the database (`app/reconcile.py`):

- **Role identity.** A role is identified by its cleaned job URL (tracking parameters, `#…` and trailing `/`
  removed). A role without its own URL (read from a heading) is identified by agency + title + location.
- **Same link as last time.** The same role row is updated: *last seen* moves on, and your status and notes stay
  attached. It is not counted as new.
- **New link.** A new role, flagged **New** until the next completed run. The first run ever is a baseline,
  so nothing is "new" on day one.
- **Reposted.** A new link with the same title at the same agency, where the old one disappeared, is treated
  as the same role with an updated link.
- **Missing.** A role absent from a *successful* check is marked "may be closed". If it's absent from the next
  successful check too, it's **removed**, and anyone who saved it sees it go. If it comes back later, it's
  reopened, not counted as new.
- **Failed checks never remove anything.** If a site times out, rate-limits (HTTP 429), or is down, its roles
  stay as they were.
- **Needs review.** An agency you reviewed stays reviewed until its careers-page text changes. Then it returns
  to the queue, and roles added by hand are flagged for a re-check.

## Deploying on a VPS (Ubuntu/Debian)

```bash
sudo adduser --system --group --home /opt/agency-roles agencyroles
sudo -u agencyroles git clone <your repo> /opt/agency-roles     # or copy the folder
cd /opt/agency-roles
sudo -u agencyroles python3 -m venv .venv
sudo -u agencyroles .venv/bin/pip install -r requirements.txt
sudo .venv/bin/python -m playwright install-deps chromium        # system libraries (needs root)
sudo -u agencyroles .venv/bin/python -m playwright install chromium

# Build the frontend (Node 18+), or build locally and copy web/dist up.
cd web && npm ci && npm run build && cd ..

sudo -u agencyroles cp .env.example .env      # then edit: PUBLIC_URL, COOKIE_SECURE=1, SMTP_* if you want emails
sudo -u agencyroles .venv/bin/python manage.py init-db
sudo -u agencyroles .venv/bin/python manage.py create-user you@example.com "Your Name" --admin

sudo cp deploy/agency-roles.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now agency-roles
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # edit the domain first
sudo systemctl reload caddy
```

- The app binds to `127.0.0.1:8000`. Caddy terminates HTTPS and gets the certificate automatically.
- Logs: `journalctl -u agency-roles -f`
- **Back up `data/app.db`.** It holds everything: users, statuses, notes, role history.
  For example, run `sqlite3 data/app.db ".backup data/backup-$(date +%F).db"` from cron.
- A 1 vCPU / 2 GB VPS is enough. The headless browser is the heaviest part.
- If the service restarts mid-run, that run is marked *Stopped: server restarted*. The next scheduled or
  manual run checks everything again.

### Loading existing CLI results

If you already ran `scrape.py`, import its cache as the first (baseline) run:

```bash
python manage.py import-cache output/cache/store_building_US
```

## Command-line scraper

`scrape.py` still works on its own and writes CSV/XLSX without the web app:

```bash
python scrape.py --browser                 # all US store-building partners → output/
python scrape.py --limit 30 --handles darkroom,anatta1 --refresh
```

Its `output/cache/` folder only lets an interrupted CLI run resume. The web app doesn't use it.

## How the scraper finds roles

1. **Listing.** `/partners/directory/services/<service>?location=<CC>` is server-rendered and returns every
   matching partner in one response.
2. **Profile.** Each partner's directory page gives the website, tier, location, team size, and LinkedIn.
3. **Careers page.** Found from scored homepage links ("Careers", "Join our team", `/careers`, links to job
   boards), then `sitemap.xml`, then common paths. Probe hits are checked against soft-404s. Social or
   booking-link "websites" and merchant-facing "hire us" pages are skipped.
4. **Roles.** Tried in this order: the public feed of the agency's job board (Greenhouse, Lever, Ashby,
   Workable, Recruitee, Breezy, SmartRecruiters, BambooHR, Personio, plus hosted JazzHR/Teamtailor/Gusto/Rippling
   pages); schema.org `JobPosting` data; job links and role titles on the careers page. With the headless
   browser on, JS-only pages are rendered, and job boards are also detected from their network requests and iframes.

Source labels in the UI: **Verified** means the role came from a job-board feed or JSON-LD. **Parsed** means it
was read from the careers page. **Check** means it was a role-like heading, so glance before applying.

## Tests

```bash
python -m pytest -q          # scraper heuristics, repeat-run reconciliation, schedule maths
cd web && npm run typecheck
```
