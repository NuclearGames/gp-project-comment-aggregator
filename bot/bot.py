import json
import logging
import os
import re
from datetime import datetime, timezone

import redis
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

REDIS_URL = os.environ["REDIS_URL"]
PACKAGE_NAME = os.environ["PACKAGE_NAME"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def _topic_slug(topic_name: str) -> str:
    return topic_name.lower().replace(" ", "_")


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def get_digest(r: redis.Redis, date_str: str) -> list[dict] | None:
    value = r.get(f"digest:{date_str}")
    return json.loads(value) if value else None


def get_reviews_for_topic(r: redis.Redis, date_str: str, topic_name: str, start: int, end: int) -> list[str]:
    key = f"reviews:{date_str}:{_topic_slug(topic_name)}"
    return r.lrange(key, start - 1, end - 1)


def build_digest_text(package_name: str, date_str: str, total_count: int, topics: list[dict]) -> str:
    lines = [
        f"📊 Daily review digest — {package_name}",
        f"Date: {date_str}  |  Reviews analysed: {total_count}",
        "",
        f"{len(topics)} complaint topics found:",
        "",
    ]
    for index, topic in enumerate(topics, start=1):
        lines.append(f"{index}. {topic.get('topic', 'Unknown Topic')} — {topic.get('count', 0)} reviews")
    lines.extend(["", 'Reply /topic "<TopicName>" 1-10 to read reviews.'])
    return "\n".join(lines)


async def start_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text(
            f"👋 Hi! I send daily review digests for {PACKAGE_NAME}.\n\n"
            "Commands:\n"
            "/digest — show today's digest\n"
            "/topic <TopicName> <start>-<end> — read reviews for a topic\n"
            "  Example: /topic Game Crashes on Launch 1-10"
        )
    except Exception:
        logger.exception("/start failed")
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


async def digest_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        date_str = datetime.now(timezone.utc).date().isoformat()
        r = _redis_client()
        digest = get_digest(r, date_str)
        if not digest:
            await update.message.reply_text("No digest available for today yet. The worker runs at 08:00 UTC.")
            return

        total_count = sum(int(item.get("count", 0)) for item in digest)
        await update.message.reply_text(build_digest_text(PACKAGE_NAME, date_str, total_count, digest))
    except Exception:
        logger.exception("/digest failed")
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


async def topic_handler(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        text = update.message.text or ""
        match = re.match(r"^/topic(?:@\w+)?\s+(.+?)\s+(\d+)-(\d+)\s*$", text)
        if not match:
            await update.message.reply_text("Usage: /topic <TopicName> <start>-<end>")
            return

        topic_name = match.group(1).strip()
        if (topic_name.startswith('"') and topic_name.endswith('"')) or (
            topic_name.startswith("'") and topic_name.endswith("'")
        ):
            topic_name = topic_name[1:-1].strip()

        start = int(match.group(2))
        end = int(match.group(3))
        if start < 1:
            start = 1
        if end < start:
            end = start
        end = min(end, start + 19)

        date_str = datetime.now(timezone.utc).date().isoformat()
        r = _redis_client()
        serialized_reviews = get_reviews_for_topic(r, date_str, topic_name, start, end)
        if not serialized_reviews:
            await update.message.reply_text("No reviews found for that topic or range.")
            return

        lines = [f'📝 "{topic_name}" — reviews {start}–{start + len(serialized_reviews) - 1}', ""]
        for idx, raw in enumerate(serialized_reviews, start=1):
            review = json.loads(raw)
            lines.append(
                f"{idx}. ⭐{review.get('rating', 0)} {review.get('author', 'Unknown')} ({review.get('date', '')})\n"
                f"   {review.get('text', '')}\n"
            )

        await update.message.reply_text("\n".join(lines))
    except Exception:
        logger.exception("/topic failed")
        await update.message.reply_text("⚠️ Something went wrong. Please try again.")


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("digest", digest_handler))
    app.add_handler(CommandHandler("topic", topic_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
