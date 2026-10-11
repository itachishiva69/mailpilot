"""Gmail API client for the requesting Telegram user's connected account."""
from __future__ import annotations

import base64
import html
import json
from html.parser import HTMLParser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import GMAIL_SCOPES
from .storage import get_credentials_json, get_user, update_user_credentials


class GmailNotConnected(RuntimeError):
    """Raised when this Telegram user has not connected Gmail."""


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif tag in {"p", "div", "br", "li"} and not self.skip_depth:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li"} and not self.skip_depth:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.text.append(data)

    def get_text(self):
        return " ".join("".join(self.text).split())


def get_gmail_service(telegram_user_id: int):
    token_json = get_credentials_json(telegram_user_id)
    user = get_user(telegram_user_id)
    if token_json is None or user is None:
        raise GmailNotConnected("Gmail is not connected. Use /connect to link your own Google account.")

    credentials_info = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(credentials_info, GMAIL_SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            update_user_credentials(telegram_user_id, creds.to_json())
        else:
            raise GmailNotConnected("Your Gmail authorization has expired. Use /connect to reconnect it.")

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def decode_body(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(data + padding)
    return decoded.decode("utf-8", errors="replace")


def extract_body(payload: dict) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")
        if body_data:
            content = decode_body(body_data)
            if mime_type == "text/plain":
                plain_parts.append(content)
            elif mime_type == "text/html":
                html_parts.append(content)
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    if plain_parts:
        return "\n".join(plain_parts).strip()
    if html_parts:
        parser = HTMLTextExtractor()
        parser.feed(html.unescape("\n".join(html_parts)))
        return parser.get_text()
    return ""


def get_recent_emails(
    max_results: int = 5,
    query: str = "in:inbox newer_than:7d",
    *,
    telegram_user_id: int,
) -> list[dict]:
    """Fetch messages only from the Gmail account linked to this Telegram user."""
    max_results = max(1, min(int(max_results), 10))
    service = get_gmail_service(telegram_user_id)
    response = (
        service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
    )

    emails = []
    for item in response.get("messages", []):
        message = (
            service.users().messages().get(
                userId="me", id=item["id"], format="full"
            ).execute()
        )
        payload = message.get("payload", {})
        headers = {
            h["name"].lower(): h["value"]
            for h in payload.get("headers", [])
        }
        emails.append({
            "id": message["id"],
            "thread_id": message.get("threadId"),
            "sender": headers.get("from", "Unknown sender"),
            "subject": headers.get("subject", "(No subject)"),
            "date": headers.get("date", "Unknown date"),
            "snippet": message.get("snippet", ""),
            "body": extract_body(payload),
            "unread": "UNREAD" in message.get("labelIds", []),
        })
    return emails
