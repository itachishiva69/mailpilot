"""Telegram interface for multi-user MailPilot."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .config import DEFAULT_DIGEST_HOUR, DEFAULT_DIGEST_MINUTE, DIGEST_TIMEZONE, TELEGRAM_BOT_TOKEN
from .email_agent import ask_mailpilot, summarize_emails
from .gmail_service import GmailNotConnected, get_recent_emails
from .oauth_flow import create_authorization_url
from .storage import (
    disconnect_user,
    get_due_digest_users,
    get_user,
    is_gmail_connected,
    mark_digest_sent,
    set_digest_preferences,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

MAX_EMAILS = 5
MAX_MESSAGE_LENGTH = 3800
TIMEZONE = ZoneInfo(DIGEST_TIMEZONE)


async def authorized(update: Update) -> bool:
    """Use only private chats so email content cannot leak into groups."""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat is None or user is None or chat.type != ChatType.PRIVATE:
        if message:
            await message.reply_text("For privacy, please chat with MailPilot in a private Telegram chat.")
        return False
    return True


def split_text(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    text = text.strip() or "No response was generated."
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(text[:split_at].strip())
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks


async def send_long_message(message, text: str) -> None:
    for chunk in split_text(text):
        await message.reply_text(chunk)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    user = get_user(update.effective_user.id)
    if user:
        message = (
            f"Welcome back to MailPilot. Gmail is connected: {user['email']}.\n\n"
            "Ask me questions naturally, or use /account, /disconnect, /digest_on and /digest_off."
        )
    else:
        message = (
            "Welcome to MailPilot! You can chat with me about general questions right away.\n\n"
            "To ask about your own email, connect your Gmail using /connect. "
            "You will sign in on Google's page; never send MailPilot your Google password.\n\n"
            "Use /help to see available options."
        )
    await update.effective_message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    await update.effective_message.reply_text(
        "Talk to MailPilot naturally, or use:\n\n"
        "/connect - Link your own Gmail account\n"
        "/account - Show connection and digest status\n"
        "/disconnect - Remove your Gmail connection\n"
        "/latest - Show recent email previews\n"
        "/unread - Show unread email previews\n"
        "/summary - Summarize recent emails\n"
        "/unreadsummary - Summarize unread emails\n"
        "/dailysummary - Summarize the last 24 hours\n"
        "/digest_on [HH:MM] - Enable daily digest (default 08:00 IST)\n"
        "/digest_off - Disable daily digest"
    )


async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    try:
        url = create_authorization_url(update.effective_user.id)
    except Exception:
        logger.exception("Could not create Google authorization URL")
        await update.effective_message.reply_text(
            "Gmail connection is not configured on the server yet. Please try again later."
        )
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Connect Gmail with Google", url=url)]])
    await update.effective_message.reply_text(
        "Connect your own Gmail account using Google's secure authorization page. "
        "MailPilot requests read-only Gmail access. Your Google password is never shared with MailPilot.",
        reply_markup=keyboard,
    )


async def account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    user = get_user(update.effective_user.id)
    if not user:
        await update.effective_message.reply_text("Gmail is not connected. Use /connect to link your own account.")
        return
    digest_time = f"{user['digest_hour']:02d}:{user['digest_minute']:02d} {DIGEST_TIMEZONE}"
    digest_state = "on" if user["digest_enabled"] else "off"
    await update.effective_message.reply_text(
        f"Connected Gmail: {user['email']}\nDaily digest: {digest_state}\nScheduled time: {digest_time}"
    )


async def disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("No Gmail account is connected to this Telegram account.")
        return
    # Remove the server-side credential first. Users can also revoke access at Google Account permissions.
    disconnect_user(user_id)
    await update.effective_message.reply_text(
        "Your Gmail connection and MailPilot's stored token have been removed. "
        "To revoke any remaining Google authorization, open https://myaccount.google.com/connections."
    )


async def show_emails(update: Update, query: str) -> None:
    if not await authorized(update):
        return
    user_id = update.effective_user.id
    if not is_gmail_connected(user_id):
        await update.effective_message.reply_text("Connect your own Gmail first with /connect.")
        return
    message = update.effective_message
    await message.reply_text("Fetching your emails...")
    try:
        emails = await asyncio.to_thread(
            get_recent_emails,
            MAX_EMAILS,
            query,
            telegram_user_id=user_id,
        )
        if not emails:
            await message.reply_text("No matching emails were found.")
            return
        for index, email in enumerate(emails, start=1):
            preview = " ".join((email.get("snippet") or email.get("body") or "No preview available.").split())[:400]
            text = (
                f"Email {index} of {len(emails)}\n\n"
                f"From: {email.get('sender', 'Unknown sender')}\n"
                f"Subject: {email.get('subject', '(No subject)')}\n"
                f"Date: {email.get('date', 'Unknown date')}\n"
                f"Unread: {'Yes' if email.get('unread') else 'No'}\n\n"
                f"Preview:\n{preview}"
            )
            await send_long_message(message, text)
    except Exception:
        logger.exception("Email retrieval failed")
        await message.reply_text("Could not retrieve your emails. If authorization expired, use /connect again.")


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_emails(update, "in:inbox newer_than:7d")


async def unread(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_emails(update, "in:inbox is:unread")


async def run_summary(update: Update, mode: str) -> None:
    if not await authorized(update):
        return
    user_id = update.effective_user.id
    if not is_gmail_connected(user_id):
        await update.effective_message.reply_text("Connect your own Gmail first with /connect.")
        return
    message = update.effective_message
    await message.reply_text("Preparing your email briefing...")
    try:
        answer = await asyncio.to_thread(summarize_emails, mode, user_id)
        await send_long_message(message, answer)
    except Exception:
        logger.exception("Email summary failed")
        await message.reply_text("I couldn't generate the briefing. If authorization expired, use /connect again.")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_summary(update, "recent")


async def unread_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_summary(update, "unread")


async def daily_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_summary(update, "daily")


async def digest_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    user_id = update.effective_user.id
    if not is_gmail_connected(user_id):
        await update.effective_message.reply_text("Connect Gmail first with /connect, then enable the digest.")
        return
    hour, minute = DEFAULT_DIGEST_HOUR, DEFAULT_DIGEST_MINUTE
    if context.args:
        try:
            parts = context.args[0].split(":", maxsplit=1)
            if len(parts) != 2:
                raise ValueError
            hour, minute = int(parts[0]), int(parts[1])
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
        except ValueError:
            await update.effective_message.reply_text("Use /digest_on or /digest_on 08:30 (24-hour time).")
            return
    set_digest_preferences(user_id, True, hour, minute)
    await update.effective_message.reply_text(f"Daily digest enabled for {hour:02d}:{minute:02d} {DIGEST_TIMEZONE}. Use /digest_off to disable it.")


async def digest_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.effective_message.reply_text("Connect Gmail first with /connect.")
        return
    set_digest_preferences(user_id, False)
    await update.effective_message.reply_text("Daily digest disabled.")


async def chat_with_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    message = update.effective_message
    user_id = update.effective_user.id
    if message is None or not message.text:
        return
    question = message.text.strip()
    if not question:
        return
    status_message = await message.reply_text("Thinking...")
    history = list(context.user_data.get("chat_history", [])[-12:])
    try:
        answer = await asyncio.to_thread(
            ask_mailpilot,
            question,
            history,
            user_id,
        )
        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])
        context.user_data["chat_history"] = history[-12:]
        try:
            await status_message.delete()
        except Exception:
            logger.debug("Could not delete status message", exc_info=True)
        await send_long_message(message, answer)
    except Exception:
        logger.exception("Natural-language agent request failed")
        try:
            await status_message.delete()
        except Exception:
            pass
        await message.reply_text("Sorry, I couldn't process that request. Please try again later.")


async def daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(TIMEZONE)
    today = now.date().isoformat()
    due_users = get_due_digest_users(today, now.hour, now.minute)
    for user in due_users:
        user_id = int(user["telegram_user_id"])
        try:
            digest = await asyncio.to_thread(summarize_emails, "daily", user_id)
            for chunk in split_text("MailPilot daily digest\n\n" + digest):
                await context.bot.send_message(chat_id=user_id, text=chunk)
            mark_digest_sent(user_id, today)
        except Exception:
            logger.exception("Daily digest failed for a connected user")
            # Do not log tokens or email bodies. Mark only after successful delivery so next day's retry remains possible.


def register_daily_digest(app: Application) -> None:
    if app.job_queue is None:
        raise RuntimeError('Install python-telegram-bot[job-queue] to enable daily digests.')
    app.job_queue.run_repeating(daily_digest, interval=60, first=15, name="multi_user_daily_digest")


def build_application() -> Application:
    """Build and configure the Telegram application for polling or webhooks."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from the environment.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    handlers = [
        ("start", start), ("help", help_command), ("connect", connect),
        ("account", account), ("disconnect", disconnect),
        ("latest", latest), ("unread", unread),
        ("summary", summary), ("unreadsummary", unread_summary),
        ("dailysummary", daily_summary), ("digest_on", digest_on), ("digest_off", digest_off),
    ]
    for command, callback in handlers:
        app.add_handler(CommandHandler(command, callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_agent))
    register_daily_digest(app)
    return app


def main() -> None:
    """Run locally using polling. Hosted deployments use app.oauth_server."""
    app = build_application()
    logger.info("Starting MailPilot Telegram bot with local polling")
    app.run_polling()


if __name__ == "__main__":
    main()
