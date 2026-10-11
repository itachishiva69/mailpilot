from app.gmail_service import get_recent_emails


def main():
    print("Connecting to Gmail...")

    emails = get_recent_emails(max_results=5)

    if not emails:
        print("No matching emails found in the last 7 days.")
        return

    print(f"\nSuccessfully fetched {len(emails)} emails.\n")

    for number, email in enumerate(emails, start=1):
        print(f"Email {number}")
        print(f"From: {email['sender']}")
        print(f"Subject: {email['subject']}")
        print(f"Date: {email['date']}")
        print(f"Unread: {email['unread']}")
        print(f"Body characters retrieved: {len(email['body'])}")
        print("-" * 50)


if __name__ == "__main__":
    main()