"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "app.db"))
WEB_DIST = Path(os.environ.get("WEB_DIST", ROOT / "web" / "dist"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# Set to 1 when served over HTTPS (behind Caddy/nginx) so the session cookie is Secure.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
# Base URL used in email links, e.g. https://jobs.example.com
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")

# Optional SMTP for email digests / watched-agency alerts.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1") == "1"

# Development/testing only: process just the first N directory agencies per run (0 = all).
RUN_LIMIT = int(os.environ.get("RUN_LIMIT", "0"))

# Delay before re-trying rate-limited agencies at the end of a run.
RETRY_DELAY_MINUTES = int(os.environ.get("RETRY_DELAY_MINUTES", "60"))
