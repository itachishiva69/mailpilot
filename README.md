# MailPilot

MailPilot is an AI-powered Telegram assistant that reads Gmail messages, answers natural-language questions, and generates email summaries.

## Features

- Natural-language conversations through Telegram
- Gmail access using OAuth 2.0
- Read-only email retrieval and search
- AI-powered email summaries using LangChain and Groq
- Unread and recent-email summaries
- Scheduled daily email digest
- Basic conversation history for follow-up questions
- Telegram chat authorization

## Architecture

- **Telegram:** User interface and message delivery
- **LangChain:** Agent orchestration and tool calling
- **Groq:** Language model inference
- **Gmail API:** Read-only email access
- **Python:** Application runtime

## Project structure

```text
mailpilot/
├── app/
│   ├── __init__.py
│   ├── bot.py
│   ├── email_agent.py
│   └── gmail_service.py
├── scripts/
│   ├── __init__.py
│   ├── test_agent.py
│   └── test_gmail.py
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── run.py
```

## Requirements

- Python and pip
- A Telegram bot token from BotFather
- A Groq API key
- A Google Cloud project with the Gmail API enabled
- Google OAuth Desktop app credentials

## Setup

Clone the repository and open its directory.

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the local configuration file:

```bash
cp .env.example .env
```

Fill in the required values in `.env`.

### Configure Gmail

1. Enable the Gmail API in Google Cloud.
2. Configure the OAuth consent screen and add your Google account as a test user when using Testing mode.
3. Create an OAuth client with the Desktop app application type.
4. Save the downloaded client credentials as `credentials.json` in the project root.
5. Run the Gmail integration test and complete Google's authorization flow.

The application generates `token.json` after successful authorization.

### Run the Gmail test

```bash
python -m scripts.test_gmail
```

### Run the agent test

```bash
python -m scripts.test_agent
```

These integration scripts may access Gmail or consume LLM API quota.

### Start MailPilot

```bash
python run.py
```

## Telegram commands

- `/start` - Start the bot
- `/help` - Show available commands
- `/latest` - Show recent email previews
- `/unread` - Show unread email previews
- `/summary` - Summarize recent emails
- `/unreadsummary` - Summarize unread emails
- `/dailysummary` - Generate a daily briefing

You can also ask questions naturally without using slash commands.

## Security and privacy

- Do not commit `.env`, `credentials.json`, or `token.json`.
- Keep the Telegram bot token and Groq API key private.
- Configure the authorized Telegram chat ID.
- Gmail access is intended to be read-only.
- Email text submitted for summarization is sent to the configured Groq model provider.
- Review the privacy implications before using the project with sensitive email accounts.

## Scheduled digests

The daily digest defaults to 8:00 AM India Standard Time. The application must be running and connected to the internet for the scheduled job to execute.

## Current limitations

- Email retrieval is bounded to a limited number of messages per tool call.
- Conversation history is held in memory and resets when the application restarts.
- Gmail OAuth Testing mode can require reauthorization.
- Model responses may need validation when interpreting deadlines or promotional claims.
