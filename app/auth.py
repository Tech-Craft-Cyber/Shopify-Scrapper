"""Users, password hashing (scrypt, stdlib), cookie sessions."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from . import db, settings

COOKIE = "session"
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def create_user(conn, email: str, name: str, password: str, is_admin: bool = False) -> int:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters.")
    with db.tx(conn):
        cur = conn.execute("INSERT INTO users (email, name, password_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
                           (email.strip(), name.strip(), hash_password(password), int(is_admin), db.now()))
    return cur.lastrowid


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=settings.SESSION_DAYS)).isoformat(timespec="seconds")
    with db.tx(conn):
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))
        conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)", (token, user_id, expires))
    return token


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(request: Request, conn=Depends(get_conn)) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        u = db.one(conn.execute(
            "SELECT u.id, u.email, u.name, u.is_admin FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ? AND s.expires_at > ?", (token, db.now())))
        if u:
            return u
    raise HTTPException(401, "Not signed in")


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(403, "Admins only")
    return user


class LoginThrottle:
    """At most 10 failed sign-ins per IP per 10 minutes."""

    def __init__(self, limit: int = 10, window: int = 600):
        self.limit, self.window = limit, window
        self.fails: dict[str, deque] = defaultdict(deque)

    def blocked(self, ip: str) -> bool:
        q = self.fails[ip]
        while q and q[0] < time.time() - self.window:
            q.popleft()
        return len(q) >= self.limit

    def fail(self, ip: str) -> None:
        self.fails[ip].append(time.time())


throttle = LoginThrottle()
