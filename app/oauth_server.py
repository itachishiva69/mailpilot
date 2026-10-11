"""FastAPI service for Google OAuth callbacks and Telegram webhooks."""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from telegram import Update

from .bot import build_application
from .config import (
    OAUTH_REDIRECT_URI,
    PUBLIC_BASE_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_SECRET,
)
from .oauth_flow import complete_authorization

logger = logging.getLogger(__name__)
telegram_application = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global telegram_application

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from the environment.")
    if not PUBLIC_BASE_URL or not PUBLIC_BASE_URL.startswith("https://"):
        raise RuntimeError(
            "PUBLIC_BASE_URL must be the deployed HTTPS URL, for example https://your-service.onrender.com"
        )
    if not TELEGRAM_WEBHOOK_SECRET:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is missing from the environment.")
    if not OAUTH_REDIRECT_URI.startswith("https://"):
        raise RuntimeError("OAUTH_REDIRECT_URI must be an HTTPS callback URL.")

    telegram_application = build_application()
    await telegram_application.initialize()
    await telegram_application.start()
    await telegram_application.bot.set_webhook(
        url=f"{PUBLIC_BASE_URL}/telegram/webhook",
        secret_token=TELEGRAM_WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
    )
    logger.info("MailPilot webhook server started")
    try:
        yield
    finally:
        try:
            await telegram_application.stop()
        finally:
            await telegram_application.shutdown()
        telegram_application = None


app = FastAPI(
    title="MailPilot",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if not TELEGRAM_WEBHOOK_SECRET or not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    if telegram_application is None:
        raise HTTPException(status_code=503, detail="Telegram application is starting")
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_application.bot)
        await telegram_application.update_queue.put(update)
    except Exception as exc:
        logger.warning("Could not accept Telegram webhook update: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Invalid Telegram update") from exc
    return {"ok": True}


@app.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        return HTMLResponse(
            "<h2>MailPilot was not connected</h2><p>You cancelled Google authorization or Google could not complete it. Return to Telegram and use /connect to try again.</p>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse(
            "<h2>Missing authorization details</h2><p>Return to Telegram and use /connect to start again.</p>",
            status_code=400,
        )
    try:
        _telegram_user_id, email = await run_in_threadpool(
            complete_authorization, state, code
        )
    except ValueError as exc:
        return HTMLResponse(
            f"<h2>Could not connect Gmail</h2><p>{escape(str(exc))}</p>",
            status_code=400,
        )
    except Exception:
        logger.exception("Google OAuth callback failed")
        return HTMLResponse(
            "<h2>MailPilot could not connect Gmail</h2><p>No credentials were displayed. Return to Telegram and try /connect again.</p>",
            status_code=500,
        )

    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>MailPilot connected</title></head>"
        "<body style='font-family:system-ui;max-width:640px;margin:60px auto;padding:0 20px'>"
        "<h2>Gmail connected successfully</h2>"
        f"<p>MailPilot linked <strong>{escape(email)}</strong> to the Telegram account that started this authorization.</p>"
        "<p>Return to your private Telegram chat with MailPilot and send /account to verify the connection.</p>"
        "<p>You may close this page.</p></body></html>",
        status_code=200,
    )
