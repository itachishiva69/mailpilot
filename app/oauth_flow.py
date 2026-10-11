"""Google web-server OAuth flow with Telegram-bound, one-time state."""
from __future__ import annotations

import json

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .config import GMAIL_SCOPES, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, OAUTH_REDIRECT_URI
from .storage import (
    consume_oauth_state,
    create_oauth_state,
    save_oauth_code_verifier,
    save_user_credentials,
)


def _flow(
    state: str | None = None,
    *,
    code_verifier: str | None = None,
    autogenerate_code_verifier: bool = False,
) -> Flow:
    missing = [
        name for name, value in (
            ("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID),
            ("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET),
            ("OAUTH_REDIRECT_URI", OAUTH_REDIRECT_URI),
        ) if not value
    ]
    if missing:
        raise RuntimeError("Missing OAuth configuration: " + ", ".join(missing))

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [OAUTH_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=GMAIL_SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=autogenerate_code_verifier,
    )
    flow.redirect_uri = OAUTH_REDIRECT_URI
    return flow


def create_authorization_url(telegram_user_id: int) -> str:
    state = create_oauth_state(telegram_user_id)
    flow = _flow(state, autogenerate_code_verifier=True)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    verifier = flow.code_verifier
    if not verifier:
        raise RuntimeError("Google OAuth did not generate a PKCE verifier.")
    save_oauth_code_verifier(state, verifier)
    return url


def complete_authorization(state: str, code: str) -> tuple[int, str]:
    pending = consume_oauth_state(state)
    if pending is None:
        raise ValueError("This authorization link is invalid or expired. Return to Telegram and use /connect again.")

    telegram_user_id, code_verifier = pending
    flow = _flow(state, code_verifier=code_verifier)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # Retrieve the email identity from the mailbox authorized by this OAuth flow.
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = gmail.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress")
    if not email:
        raise RuntimeError("Google authorized the account but did not return its Gmail address.")

    save_user_credentials(telegram_user_id, email, credentials.to_json())
    return telegram_user_id, email
