# Multi-user deployment patch notes

This patch adapts MailPilot for multi-user Telegram use and deployment on Render with Neon PostgreSQL.

## Main changes
- Replaces the single fixed Gmail token with per-Telegram-user OAuth credentials.
- Stores OAuth state, encrypted credentials, and digest settings in PostgreSQL via `DATABASE_URL`.
- Uses Google OAuth Web application flow.
- Uses Telegram webhooks through FastAPI instead of long polling for hosted deployment.
- Includes a Render Blueprint and updated deployment README.

## Critical launch requirements
1. Set `DATABASE_URL` to your Neon PostgreSQL URI, including SSL parameters.
2. Keep `TOKEN_ENCRYPTION_KEY` stable and backed up.
3. Set Telegram/Groq/Google OAuth secrets as Render environment variables.
4. After Render assigns a real HTTPS hostname, register `https://YOUR-SERVICE.onrender.com/oauth/callback` as the exact Google OAuth Authorized redirect URI.
5. Keep one active deployment per Telegram bot token.
6. Test account isolation with two Telegram accounts.
7. Review Google's verification and security assessment requirements for the restricted `gmail.readonly` scope before public launch.
8. Render Free services sleep when idle; scheduled delivery is not guaranteed while asleep.
