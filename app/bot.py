
import asyncio
import logging
import os
from datetime import time
from zoneinfo import ZoneInfo

from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .gmail_service import get_recent_emails
from .email_agent import ask_mailpilot, summarize_emails


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv(
    dotenv_path=Path(__file__).resolve().parent.parent / ".env"
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_CHAT_ID")

DIGEST_ENABLED = (
    os.getenv("DAILY_DIGEST_ENABLED", "true")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)

DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "8"))
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE", "0"))

TIMEZONE = ZoneInfo("Asia/Kolkata")

MAX_EMAILS = 5
MAX_MESSAGE_LENGTH = 3800


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Prevent HTTP request logs from printing Telegram bot
# API URLs that contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)


# --------------------------------------------------
# Authorization
# --------------------------------------------------

async def authorized(update: Update) -> bool:
    """Allow email operations only from the configured chat."""

    chat = update.effective_chat
    message = update.effective_message

    is_authorized = (
        chat is not None
        and ALLOWED_CHAT_ID is not None
        and str(chat.id) == ALLOWED_CHAT_ID.strip()
    )

    if not is_authorized:
        if message is not None:
            await message.reply_text(
                "Unauthorized. Email access is restricted."
            )
        return False

    return True


# --------------------------------------------------
# Telegram message utilities
# --------------------------------------------------

def split_text(
    text: str,
    limit: int = MAX_MESSAGE_LENGTH,
) -> list[str]:
    """Split long responses into Telegram-sized messages."""

    text = text.strip() or "No summary was generated."
    chunks = []

    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)

        # Avoid creating very short chunks.
        if split_at < limit // 2:
            split_at = limit

        chunks.append(text[:split_at].strip())
        text = text[split_at:].lstrip()

    if text:
        chunks.append(text)

    return chunks


async def send_long_message(message, text: str) -> None:
    """Send a potentially long response in separate messages."""

    for chunk in split_text(text):
        await message.reply_text(chunk)


# --------------------------------------------------
# Basic commands
# --------------------------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await authorized(update):
        return

    message = update.effective_message

    await message.reply_text(
        "Welcome to MailPilot!\n\n"
        "Your AI email assistant is ready.\n\n"
        "Available commands:\n\n"
        "/summary - Summarize recent emails\n"
        "/unreadsummary - Summarize unread emails\n"
        "/dailysummary - Generate a daily briefing\n"
        "/latest - Show recent email previews\n"
        "/unread - Show unread email previews\n"
        "/help - Show available commands"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await authorized(update):
        return

    await update.effective_message.reply_text(
        "MailPilot Commands\n\n"
        "/start - Start the bot\n"
        "/help - Show commands\n"
        "/latest - Show recent inbox emails\n"
        "/unread - Show unread inbox emails\n"
        "/summary - AI summary of recent emails\n"
        "/unreadsummary - AI summary of unread emails\n"
        "/dailysummary - AI summary of the last 24 hours\n\n"
        "Automatic daily digests run at the configured time "
        "while MailPilot is running."
    )


# --------------------------------------------------
# Email preview commands
# --------------------------------------------------

async def show_emails(
    update: Update,
    query: str,
) -> None:
    """Retrieve emails and send compact previews to Telegram."""

    if not await authorized(update):
        return

    message = update.effective_message

    await message.reply_text("Fetching emails...")

    try:
        emails = await asyncio.to_thread(
            get_recent_emails,
            max_results=MAX_EMAILS,
            query=query,
        )

        if not emails:
            await message.reply_text(
                "No matching emails were found."
            )
            return

        for index, email in enumerate(emails, start=1):
            preview = (
                email.get("snippet")
                or email.get("body")
                or "No preview available."
            )

            preview = " ".join(preview.split())[:400]

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

        await message.reply_text(
            "Could not retrieve emails. "
            "Check the application logs."
        )


async def latest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await show_emails(
        update,
        "in:inbox newer_than:7d",
    )


async def unread(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await show_emails(
        update,
        "in:inbox is:unread",
    )


# --------------------------------------------------
# AI summarization commands
# --------------------------------------------------

async def run_summary(
    update: Update,
    mode: str,
) -> None:
    """Run the LangChain agent without blocking Telegram polling."""

    if not await authorized(update):
        return

    message = update.effective_message

    status_messages = {
        "recent": "Reading recent emails and preparing your AI briefing...",
        "unread": "Reading unread emails and preparing your AI briefing...",
        "daily": "Preparing your daily email briefing...",
    }

    await message.reply_text(
        status_messages.get(mode, "Preparing your email briefing...")
    )

    try:
        summary_text = await asyncio.to_thread(
            summarize_emails,
            mode,
        )

        await send_long_message(message, summary_text)

    except Exception:
        logger.exception(
            "AI email summarization failed for mode %s",
            mode,
        )

        await message.reply_text(
            "Sorry, I could not generate the email briefing. "
            "Check the terminal logs for details."
        )


async def summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await run_summary(update, "recent")


async def unread_summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await run_summary(update, "unread")


async def daily_summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await run_summary(update, "daily")


# --------------------------------------------------
# Automatic daily digest
# --------------------------------------------------

async def daily_digest(
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Generate and deliver the scheduled daily briefing."""

    if not ALLOWED_CHAT_ID:
        logger.error(
            "Cannot send daily digest: chat ID is not configured."
        )
        return

    chat_id = int(ALLOWED_CHAT_ID.strip())

    try:
        logger.info("Generating scheduled daily email digest")

        summary_text = await asyncio.to_thread(
            summarize_emails,
            "daily",
        )

        digest = (
            "MailPilot: Daily Email Digest\n\n"
            f"{summary_text}"
        )

        for chunk in split_text(digest):
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
            )

        logger.info("Daily email digest sent successfully")

    except Exception:
        logger.exception("Scheduled daily digest failed")

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "MailPilot could not generate today's digest. "
                    "Check the application logs."
                ),
            )
        except Exception:
            logger.exception(
                "Could not send the daily digest error notification"
            )

async def chat_with_agent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle ordinary text messages using the AI agent."""

    if not await authorized(update):
        return

    message = update.effective_message

    if message is None or not message.text:
        return

    question = message.text.strip()

    if not question:
        return

    status_message = await message.reply_text(
        "Thinking..."
    )

    # Keep up to six previous conversation turns.
    history = context.user_data.get(
        "chat_history",
        [],
    )

    recent_history = list(history[-12:])

    try:
        answer = await asyncio.to_thread(
            ask_mailpilot,
            question,
            recent_history,
        )

        # Save text-only conversation history in memory.
        history.extend(
            [
                {
                    "role": "user",
                    "content": question,
                },
                {
                    "role": "assistant",
                    "content": answer,
                },
            ]
        )

        context.user_data["chat_history"] = history[-12:]

        # Remove the temporary status message.
        try:
            await status_message.delete()
        except Exception:
            logger.debug(
                "Could not remove status message",
                exc_info=True,
            )

        await send_long_message(
            message,
            answer,
        )

    except Exception:
        logger.exception(
            "Natural-language agent request failed"
        )

        try:
            await status_message.delete()
        except Exception:
            pass

        await message.reply_text(
            "Sorry, I couldn't process that request. "
            "Please try again. Check the application logs "
            "if the problem continues."
        )

def schedule_daily_digest(app: Application) -> None:
    """Register the digest job using India Standard Time."""

    if not DIGEST_ENABLED:
        logger.info("Automatic daily digest is disabled")
        return

    if app.job_queue is None:
        raise RuntimeError(
            'JobQueue is unavailable. Install it with:\n'
            'pip install "python-telegram-bot[job-queue]>=22,<23"'
        )

    if not 0 <= DIGEST_HOUR <= 23:
        raise ValueError("DIGEST_HOUR must be between 0 and 23")

    if not 0 <= DIGEST_MINUTE <= 59:
        raise ValueError("DIGEST_MINUTE must be between 0 and 59")

    digest_time = time(
        hour=DIGEST_HOUR,
        minute=DIGEST_MINUTE,
        tzinfo=TIMEZONE,
    )

    app.job_queue.run_daily(
        daily_digest,
        time=digest_time,
        name="mailpilot_daily_digest",
    )

    logger.info(
        "Daily digest scheduled for %02d:%02d Asia/Kolkata",
        DIGEST_HOUR,
        DIGEST_MINUTE,
    )


# --------------------------------------------------
# Application entry point
# --------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing from .env"
        )

    if not ALLOWED_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_ALLOWED_CHAT_ID is missing from .env"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Register commands.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(CommandHandler("unread", unread))

    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(
        CommandHandler("unreadsummary", unread_summary)
    )
    app.add_handler(
        CommandHandler("dailysummary", daily_summary)
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat_with_agent,
        )
    )

    # Register the scheduled job.
    schedule_daily_digest(app)

    logger.info("Starting MailPilot...")
    app.run_polling()


if __name__ == "__main__":
    main()
