"""Manual Gmail integration test for a previously connected Telegram user.

Set TEST_TELEGRAM_USER_ID in the environment to the numeric Telegram user ID
that has connected Gmail via /connect.
"""
import os
from app.gmail_service import get_recent_emails

if __name__ == "__main__":
    raw_id = os.getenv("TEST_TELEGRAM_USER_ID", "").strip()
    if not raw_id.isdigit():
        raise SystemExit("Set TEST_TELEGRAM_USER_ID to a connected Telegram user's numeric ID.")
    emails = get_recent_emails(
        max_results=5,
        query="in:inbox newer_than:7d",
        telegram_user_id=int(raw_id),
    )
    print(f"Retrieved {len(emails)} messages.")
    for item in emails:
        print(f"From: {item['sender']} | Subject: {item['subject']} | Unread: {item['unread']}")
