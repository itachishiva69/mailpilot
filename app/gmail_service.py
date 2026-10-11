import base64
import html
import os
from html.parser import HTMLParser
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent.parent

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class HTMLTextExtractor(HTMLParser):
    """Extract readable text from HTML email bodies."""

    def __init__(self):
        super().__init__()
        self.text = []
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


def get_gmail_service():
    """Authorize the user and create a Gmail API client."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json is missing from the project directory."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


def decode_body(data):
    """Decode Gmail's URL-safe Base64 message content."""
    if not data:
        return ""

    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(data + padding)

    return decoded.decode("utf-8", errors="replace")


def extract_body(payload):
    """Prefer plain text, falling back to HTML."""
    plain_parts = []
    html_parts = []

    def walk(part):
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
    max_results=5,
    query="in:inbox newer_than:7d",
):
    """Fetch recent inbox messages without modifying them."""
    max_results = max(1, min(max_results, 10))
    service = get_gmail_service()

    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max_results,
        )
        .execute()
    )

    emails = []

    for item in response.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="full",
            )
            .execute()
        )

        payload = message.get("payload", {})
        headers = {
            header["name"].lower(): header["value"]
            for header in payload.get("headers", [])
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