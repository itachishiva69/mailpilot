from app.email_agent import summarize_emails


if __name__ == "__main__":
    print("Generating your recent-email briefing...\n")

    summary = summarize_emails("recent")

    print(summary)