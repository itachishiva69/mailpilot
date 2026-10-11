"""Shared configuration for MailPilot."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
).strip().rstrip("/")
OAUTH_REDIRECT_URI = (
    os.getenv("OAUTH_REDIRECT_URI", "").strip()
    or (f"{PUBLIC_BASE_URL}/oauth/callback" if PUBLIC_BASE_URL else "")
)
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

DIGEST_TIMEZONE = os.getenv("DIGEST_TIMEZONE", "Asia/Kolkata").strip()
DEFAULT_DIGEST_HOUR = int(os.getenv("DEFAULT_DIGEST_HOUR", "8"))
DEFAULT_DIGEST_MINUTE = int(os.getenv("DEFAULT_DIGEST_MINUTE", "0"))
PORT = int(os.getenv("PORT", "8000"))

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
