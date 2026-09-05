"""
Authentication module — JWT + bcrypt, single-tenant now, multi-tenant ready.

Tables managed in PostgreSQL (shared pool from db.py).
All tokens are validated before any patient data is returned.

JWT flow:
  POST /auth/login  → access_token (JSON body, 8h) + refresh_token (HttpOnly cookie, 30d)
  POST /auth/refresh → new access_token; refresh token rotated
  POST /auth/logout  → refresh token deleted server-side
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from db import _conn

# ── Secret key ─────────────────────────────────────────────────────────────────
# Generated once on first run and saved to auth_secret.key (gitignored).
# Set AUTH_JWT_SECRET env var to override (for cloud deployment).
_SECRET_FILE = "auth_secret.key"

def _load_or_create_secret() -> str:
    env_secret = os.environ.get("AUTH_JWT_SECRET")
    if env_secret:
        return env_secret
    if os.path.exists(_SECRET_FILE):
        return open(_SECRET_FILE).read().strip()
    secret = secrets.token_hex(32)
    with open(_SECRET_FILE, "w") as f:
        f.write(secret)
    return secret

JWT_SECRET      = _load_or_create_secret()
JWT_ALGORITHM   = "HS256"
ACCESS_TOKEN_MINUTES  = int(os.environ.get("AUTH_ACCESS_TOKEN_MINUTES", "480"))   # 8h = one workday
REFRESH_TOKEN_DAYS    = int(os.environ.get("AUTH_REFRESH_TOKEN_DAYS", "30"))  # 30d = monthly re-login

# ── Database ────────────────────────────────────────────────────────────────────

_CREATE_CLINICS = """
    CREATE TABLE IF NOT EXISTS clinics (
        id         SERIAL PRIMARY KEY,
        slug       TEXT    NOT NULL UNIQUE,
        name       TEXT    NOT NULL,
        created_at TEXT    NOT NULL DEFAULT NOW()::text
    )
"""

_CREATE_USERS = """
    CREATE TABLE IF NOT EXISTS users (
        id                   SERIAL PRIMARY KEY,
        clinic_id            INTEGER NOT NULL REFERENCES clinics(id),
        username             TEXT    NOT NULL,
        display_name         TEXT    NOT NULL,
        role                 TEXT    NOT NULL CHECK (role IN ('admin', 'nurse')),
        password_hash        TEXT    NOT NULL,
        is_active            INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at           TEXT    NOT NULL DEFAULT NOW()::text,
        created_by           INTEGER REFERENCES users(id),
        UNIQUE (clinic_id, username)
    )
"""

_CREATE_REFRESH_TOKENS = """
    CREATE TABLE IF NOT EXISTS refresh_tokens (
        id           SERIAL PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id),
        token_hash   TEXT    NOT NULL UNIQUE,
        expires_at   TEXT    NOT NULL,
        created_at   TEXT    NOT NULL DEFAULT NOW()::text,
        last_used_at TEXT
    )
"""


def init() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_CLINICS)
            cur.execute(_CREATE_USERS)
            cur.execute(_CREATE_REFRESH_TOKENS)


# ── Bootstrap ───────────────────────────────────────────────────────────────────

def has_any_users(clinic_id: int = 1) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE clinic_id = %s", (clinic_id,)
            )
            return cur.fetchone()["cnt"] > 0


def bootstrap_clinic(clinic_slug: str, clinic_name: str,
                     admin_username: str, admin_password: str,
                     nurse_names: list[str], nurse_password: str) -> None:
    """Create clinic_id=1, admin account, and nurse accounts on first run."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clinics (id, slug, name) VALUES (1, %s, %s) ON CONFLICT DO NOTHING",
                (clinic_slug, clinic_name)
            )
            admin_hash = hash_password(admin_password)
            cur.execute(
                """INSERT INTO users
                   (clinic_id, username, display_name, role, password_hash, must_change_password)
                   VALUES (1, %s, %s, 'admin', %s, 0)
                   ON CONFLICT DO NOTHING""",
                (admin_username, admin_username, admin_hash)
            )
            nurse_hash = hash_password(nurse_password)
            for name in nurse_names:
                cur.execute(
                    """INSERT INTO users
                       (clinic_id, username, display_name, role, password_hash, must_change_password)
                       VALUES (1, %s, %s, 'nurse', %s, 1)
                       ON CONFLICT DO NOTHING""",
                    (name, name, nurse_hash)
                )


# ── Password helpers ────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── User lookup ─────────────────────────────────────────────────────────────────

def get_user_by_username(clinic_id: int, username: str) -> Optional[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE clinic_id = %s AND username = %s AND is_active = 1",
                (clinic_id, username)
            )
            row = cur.fetchone()
    return dict(row) if row is not None else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE id = %s AND is_active = 1", (user_id,)
            )
            row = cur.fetchone()
    return dict(row) if row is not None else None


def list_users(clinic_id: int) -> list:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, display_name, role, is_active, must_change_password, created_at
                   FROM users WHERE clinic_id = %s ORDER BY role DESC, display_name""",
                (clinic_id,)
            )
            return [dict(r) for r in cur.fetchall()]


def create_user(clinic_id: int, username: str, display_name: str,
                role: str, password: str, created_by: int) -> int:
    pw_hash = hash_password(password)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users
                   (clinic_id, username, display_name, role, password_hash, must_change_password, created_by)
                   VALUES (%s, %s, %s, %s, %s, 1, %s)
                   RETURNING id""",
                (clinic_id, username, display_name, role, pw_hash, created_by)
            )
            return cur.fetchone()["id"]


def update_password(user_id: int, clinic_id: int, new_password: str) -> None:
    pw_hash = hash_password(new_password)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s, must_change_password = 0 WHERE id = %s AND clinic_id = %s",
                (pw_hash, user_id, clinic_id)
            )


def change_own_password(user_id: int, clinic_id: int, old_password: str, new_password: str) -> None:
    if len(new_password) < 6:
        raise ValueError("新密碼至少需要 6 個字元")
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM users WHERE id = %s AND clinic_id = %s AND is_active = 1",
                (user_id, clinic_id)
            )
            row = cur.fetchone()
            if not row or not verify_password(old_password, row["password_hash"]):
                raise ValueError("目前密碼不正確")
            pw_hash = hash_password(new_password)
            cur.execute(
                "UPDATE users SET password_hash = %s, must_change_password = 0 WHERE id = %s AND clinic_id = %s",
                (pw_hash, user_id, clinic_id)
            )


def update_username(user_id: int, clinic_id: int, new_username: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE username = %s AND clinic_id = %s AND id != %s",
                (new_username, clinic_id, user_id)
            )
            if cur.fetchone():
                raise ValueError("帳號名稱已被使用")
            cur.execute(
                "UPDATE users SET username = %s WHERE id = %s AND clinic_id = %s",
                (new_username, user_id, clinic_id)
            )


def deactivate_user(user_id: int, clinic_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_active = 0 WHERE id = %s AND clinic_id = %s",
                (user_id, clinic_id)
            )
            cur.execute(
                "DELETE FROM refresh_tokens WHERE user_id = %s", (user_id,)
            )


def reactivate_user(user_id: int, clinic_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_active = 1 WHERE id = %s AND clinic_id = %s",
                (user_id, clinic_id)
            )


def get_all_users_including_inactive(clinic_id: int) -> list:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, username, display_name, role, is_active, must_change_password, created_at
                   FROM users WHERE clinic_id = %s ORDER BY role DESC, display_name""",
                (clinic_id,)
            )
            return [dict(r) for r in cur.fetchall()]


# ── JWT tokens ──────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, clinic_id: int, role: str, display_name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": str(user_id),
        "clinic_id": clinic_id,
        "role": role,
        "display_name": display_name,
        "exp": exp,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── Refresh tokens ──────────────────────────────────────────────────────────────

def create_refresh_token(user_id: int) -> str:
    """Create and store a refresh token; return the raw (unhashed) token."""
    raw = secrets.token_hex(32)
    token_hash = _hash_refresh_token(raw)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, token_hash, expires_at)
            )
    return raw


def rotate_refresh_token(old_raw: str) -> tuple[str, int]:
    """Validate old token, delete it, issue a new one. Returns (new_raw, user_id)."""
    old_hash = _hash_refresh_token(old_raw)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, expires_at FROM refresh_tokens WHERE token_hash = %s",
                (old_hash,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="Session 已過期，請重新登入")
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at < datetime.now(timezone.utc):
                cur.execute("DELETE FROM refresh_tokens WHERE id = %s", (row["id"],))
                raise HTTPException(status_code=401, detail="Session 已過期，請重新登入")
            cur.execute("DELETE FROM refresh_tokens WHERE id = %s", (row["id"],))
            user_id = row["user_id"]

    new_raw = secrets.token_hex(32)
    new_hash = _hash_refresh_token(new_raw)
    new_expires = (datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (user_id, new_hash, new_expires)
            )
    return new_raw, user_id


def delete_refresh_token(raw: str) -> None:
    token_hash = _hash_refresh_token(raw)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM refresh_tokens WHERE token_hash = %s", (token_hash,))


def _hash_refresh_token(raw: str) -> str:
    import hashlib
    return hashlib.sha256(raw.encode()).hexdigest()


def purge_expired_refresh_tokens() -> None:
    now_str = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM refresh_tokens WHERE expires_at < %s", (now_str,)
            )


# ── FastAPI dependencies ────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, user_id: int, clinic_id: int, role: str, display_name: str):
        self.user_id      = user_id
        self.clinic_id    = clinic_id
        self.role         = role
        self.display_name = display_name


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="請先登入")
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="憑證無效或已過期，請重新登入")
    return CurrentUser(
        user_id=int(payload["sub"]),
        clinic_id=payload["clinic_id"],
        role=payload["role"],
        display_name=payload["display_name"],
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="此功能需要管理員權限")
    return user
