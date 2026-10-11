# MailPilot

MailPilot is a multi-user Telegram email assistant. Each person connects their own Gmail account with Google's OAuth flow; the bot never asks for a Google password.

## Features

- Natural-language Telegram chat
- Per-Telegram-user Gmail OAuth connection
- Read-only Gmail retrieval and search
- LangChain agent powered by Groq
- Encrypted OAuth tokens stored in Neon PostgreSQL
- Per-user digest preferences
- HTTPS Google OAuth callback and Telegram webhook
- `/connect`, `/account`, `/disconnect`, `/latest`, `/unread`, `/summary`, `/unreadsummary`, `/dailysummary`, `/digest_on`, and `/digest_off`

## Architecture

- Telegram sends updates to the hosted HTTPS webhook.
- FastAPI serves the Telegram webhook and Google OAuth callback.
- Neon PostgreSQL stores account metadata, one-time OAuth states, encrypted Google tokens, and digest preferences.
- Fernet encrypts token JSON before it is stored in PostgreSQL.
- Gmail tools are constructed for the requesting Telegram user and load only that user's connected OAuth credentials.
- Groq receives email text when the user asks MailPilot to summarize or discuss messages.

## Local setup

Requires Python 3.11+ (test your target version and current dependencies before production rollout).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set at least `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `DATABASE_URL`, and `TOKEN_ENCRYPTION_KEY`. For hosted OAuth, also configure a Google Web application OAuth client and the public HTTPS URLs below.

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key safe and persistent. If it is lost, saved OAuth tokens cannot be decrypted. Never commit `.env`, the Neon connection URI, OAuth secrets, or the encryption key.

## Neon PostgreSQL

1. Create a Neon project.
2. In the Neon Console, click **Connect**.
3. Choose the branch, database, and role. Enable **Pooled connection** for the application if available.
4. Copy the PostgreSQL connection URI and set it as `DATABASE_URL` in the host's environment variables. It contains a password, so do not paste it into chats or commit it to Git.
5. The application creates its tables at startup.

Use a Neon URI with SSL enabled, as provided by the Neon Console (`sslmode=require`).

## Deploy on Render

The repository includes `render.yaml` for a Render Web Service. Connect the GitHub repository in Render and create the service from the Blueprint, or create a Web Service manually with:

- Build command: `pip install -r requirements.txt`
- Start command: `python run.py`
- Health check path: `/healthz`

Configure these environment variables in Render:

- `TELEGRAM_BOT_TOKEN`: token from BotFather
- `GROQ_API_KEY`: Groq API key
- `GROQ_MODEL`: optional; defaults to `openai/gpt-oss-20b`
- `DATABASE_URL`: Neon PostgreSQL connection URI
- `TOKEN_ENCRYPTION_KEY`: persistent Fernet key
- `TELEGRAM_WEBHOOK_SECRET`: generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `GOOGLE_CLIENT_ID`: client ID from a Google OAuth **Web application** client
- `GOOGLE_CLIENT_SECRET`: client secret from that Web application client

Render sets `RENDER_EXTERNAL_URL` for the service. MailPilot uses it to derive `PUBLIC_BASE_URL` and `OAUTH_REDIRECT_URI`, unless explicitly overridden. After Render has created the service, verify the redirect URI shown in the logs/configuration is exactly `https://YOUR-SERVICE.onrender.com/oauth/callback` (replace with the actual Render hostname).

## Google OAuth setup

1. In Google Cloud, enable Gmail API.
2. Configure the OAuth consent screen and test users while developing.
3. Create an OAuth client with application type **Web application** (the Desktop client from local development is not the right client for this hosted callback).
4. Add the exact redirect URI `https://YOUR-SERVICE.onrender.com/oauth/callback` to **Authorized redirect URIs** after Render provides the real service URL.
5. Set the Web client ID and secret in Render.
6. Keep the app in Testing mode for private testing; add test accounts to the test-user list.

The `gmail.readonly` scope is restricted. Before offering unrestricted public access, review Google's current OAuth verification, privacy policy, and security assessment requirements. Do not claim the public release is approved until Google has approved the applicable requirements.

## First use

1. Open the Telegram bot and send `/start`.
2. Send `/connect` and tap **Connect Gmail with Google**.
3. Sign in with the Google account you want MailPilot to read and approve the requested scope.
4. Return to Telegram and send `/account`.
5. Ask a natural-language email question.

An unconnected user can ask general questions, but Gmail tools should not retrieve email until that user's own Gmail is connected.

## Important deployment limitations

- Render Free web services spin down after inactivity; the first webhook request after sleep can be delayed. A free instance can restart at any time.
- Scheduled digests are not guaranteed while the service is asleep. For reliable scheduled delivery, use an always-on plan or a separate scheduler that wakes the service safely.
- Test multi-user isolation with two different Telegram accounts before inviting users.
- Keep only one deployment connected to a given Telegram bot token; webhook configuration is shared per bot.

## Privacy and security

- Never ask users for Google passwords.
- OAuth tokens are encrypted before they are stored in Neon. Protect both `DATABASE_URL` and `TOKEN_ENCRYPTION_KEY`.
- Do not log access tokens, refresh tokens, or email bodies.
- `/disconnect` removes MailPilot's saved credentials; users can also revoke the app through their Google Account permissions.
- Email content sent to Groq is processed by that provider. Make this clear to users in a public privacy notice before launch.
- Review the full Git history before public launch to ensure secrets were never committed. If a secret was committed, rotate it; deleting the current file does not remove it from history.

## Tests

```bash
python -m py_compile run.py app/*.py scripts/*.py
```

The Gmail integration test requires a connected Telegram user's numeric ID in `TEST_TELEGRAM_USER_ID` and a working `DATABASE_URL`:

```bash
TEST_TELEGRAM_USER_ID=123456789 python -m scripts.test_gmail
```

The agent smoke test requires `GROQ_API_KEY` and the database environment because the package uses persistent storage:

```bash
python -m scripts.test_agent
```
