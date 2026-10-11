"""PostgreSQL persistence for per-user OAuth credentials and preferences."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from cryptography.fernet import Fernet, InvalidToken

from .config import DATABASE_URL, TOKEN_ENCRYPTION_KEY


def _connect() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Configure the Neon PostgreSQL connection string."
        )
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                telegram_user_id BIGINT PRIMARY KEY,
                email TEXT NOT NULL,
                credentials_encrypted TEXT NOT NULL,
                digest_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                digest_hour SMALLINT NOT NULL DEFAULT 8,
                digest_minute SMALLINT NOT NULL DEFAULT 0,
                last_digest_date DATE,
                connected_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                telegram_user_id BIGINT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_digest ON users(digest_enabled, digest_hour, digest_minute)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_oauth_states_created_at ON oauth_states(created_at)"
        )
        conn.execute(
            "ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS code_verifier TEXT"
        )


def _fernet() -> Fernet:
    if not TOKEN_ENCRYPTION_KEY:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is missing. Generate a Fernet key and set it in the environment."
        )
    try:
        return Fernet(TOKEN_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_oauth_state(telegram_user_id: int) -> str:
    state = secrets.token_urlsafe(32)
    now = time.time()
    with _connect() as conn:
        conn.execute("DELETE FROM oauth_states WHERE created_at < %s", (now - 3600,))
        conn.execute(
            "INSERT INTO oauth_states(state, telegram_user_id, created_at) VALUES (%s, %s, %s)",
            (state, int(telegram_user_id), now),
        )
    return state


def save_oauth_code_verifier(state: str, code_verifier: str) -> None:
    """Persist the PKCE verifier for this one-time OAuth state."""
    if not code_verifier:
        raise ValueError("OAuth code verifier cannot be empty.")
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE oauth_states SET code_verifier = %s WHERE state = %s",
            (code_verifier, state),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Could not save the OAuth code verifier.")


def consume_oauth_state(
    state: str, max_age_seconds: int = 600
) -> tuple[int, str] | None:
    """Consume a one-time OAuth state and return its user ID and PKCE verifier."""
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT telegram_user_id, created_at, code_verifier "
            "FROM oauth_states WHERE state = %s FOR UPDATE",
            (state,),
        ).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = %s", (state,))
        if (
            row is None
            or now - float(row["created_at"]) > max_age_seconds
            or not row["code_verifier"]
        ):
            return None
        return int(row["telegram_user_id"]), str(row["code_verifier"])


def save_user_credentials(telegram_user_id: int, email: str, credentials_json: str) -> None:
    encrypted = _fernet().encrypt(credentials_json.encode("utf-8")).decode("ascii")
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO users (
                telegram_user_id, email, credentials_encrypted,
                digest_enabled, digest_hour, digest_minute,
                last_digest_date, connected_at, updated_at
            ) VALUES (%s, %s, %s, FALSE, 8, 0, NULL, %s, %s)
            ON CONFLICT (telegram_user_id) DO UPDATE SET
                email = EXCLUDED.email,
                credentials_encrypted = EXCLUDED.credentials_encrypted,
                updated_at = EXCLUDED.updated_at""",
            (int(telegram_user_id), email, encrypted, now, now),
        )


def update_user_credentials(telegram_user_id: int, credentials_json: str) -> None:
    encrypted = _fernet().encrypt(credentials_json.encode("utf-8")).decode("ascii")
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE users SET credentials_encrypted = %s, updated_at = %s WHERE telegram_user_id = %s",
            (encrypted, _now(), int(telegram_user_id)),
        )
        if cursor.rowcount == 0:
            raise RuntimeError("Gmail is not connected for this Telegram account. Use /connect.")


def get_credentials_json(telegram_user_id: int) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT credentials_encrypted FROM users WHERE telegram_user_id = %s",
            (int(telegram_user_id),),
        ).fetchone()
    if row is None:
        return None
    try:
        return _fernet().decrypt(row["credentials_encrypted"].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Saved Gmail credentials could not be decrypted. Check TOKEN_ENCRYPTION_KEY.") from exc


def get_user(telegram_user_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """SELECT telegram_user_id, email, digest_enabled, digest_hour,
                      digest_minute, last_digest_date, connected_at
               FROM users WHERE telegram_user_id = %s""",
            (int(telegram_user_id),),
        ).fetchone()
    return dict(row) if row else None


def is_gmail_connected(telegram_user_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE telegram_user_id = %s AND credentials_encrypted IS NOT NULL",
            (int(telegram_user_id),),
        ).fetchone()
    return row is not None


def disconnect_user(telegram_user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM users WHERE telegram_user_id = %s", (int(telegram_user_id),))
        conn.execute("DELETE FROM oauth_states WHERE telegram_user_id = %s", (int(telegram_user_id),))


def set_digest_preferences(
    telegram_user_id: int,
    enabled: bool,
    hour: int | None = None,
    minute: int | None = None,
) -> bool:
    if hour is not None and not 0 <= hour <= 23:
        raise ValueError("hour must be between 0 and 23")
    if minute is not None and not 0 <= minute <= 59:
        raise ValueError("minute must be between 0 and 59")
    with _connect() as conn:
        row = conn.execute(
            "SELECT digest_hour, digest_minute FROM users WHERE telegram_user_id = %s",
            (int(telegram_user_id),),
        ).fetchone()
        if row is None:
            return False
        new_hour = int(row["digest_hour"]) if hour is None else hour
        new_minute = int(row["digest_minute"]) if minute is None else minute
        conn.execute(
            "UPDATE users SET digest_enabled = %s, digest_hour = %s, digest_minute = %s, updated_at = %s WHERE telegram_user_id = %s",
            (bool(enabled), new_hour, new_minute, _now(), int(telegram_user_id)),
        )
    return True


def get_due_digest_users(today: str, hour: int, minute: int) -> list[dict[str, Any]]:
    """Return due digests not sent today, including those delayed by host sleep."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT telegram_user_id, email FROM users
               WHERE digest_enabled = TRUE
                 AND (digest_hour < %s OR (digest_hour = %s AND digest_minute <= %s))
                 AND (last_digest_date IS NULL OR last_digest_date <> %s::date)""",
            (hour, hour, minute, today),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_digest_sent(telegram_user_id: int, today: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET last_digest_date = %s::date, updated_at = %s WHERE telegram_user_id = %s",
            (today, _now(), int(telegram_user_id)),
        )


init_db()
