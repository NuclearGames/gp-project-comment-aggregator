import logging
import os
import sys
from datetime import datetime, timezone

import requests
from analyze import analyze_reviews
from fetch_reviews import fetch_recent_reviews
from store import get_redis_client, save_digest

from shared.digest import build_digest_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def send_telegram_message(text: str) -> None:
    """Send a text message to the configured Telegram chat.

    Args:
        text: Message body to send.

    Returns:
        None.

    Raises:
        requests.HTTPError: If Telegram returns a non-OK response.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": None},
        timeout=30,
    )
    if response.ok:
        logger.info("Digest message sent successfully to Telegram")
    else:
        logger.error(
            "Telegram send failed: status=%s body=%s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()


def main() -> int:
    """Run the worker job to fetch, analyze, store, and notify.

    Args:
        None.

    Returns:
        Process exit code: 0 on success, 1 on failure.
    """
    try:
        package_name = os.environ["PACKAGE_NAME"]
        date_str = datetime.now(timezone.utc).date().isoformat()

        reviews = fetch_recent_reviews()
        logger.info("Fetched %s reviews", len(reviews))

        try:
            topics = analyze_reviews(reviews)
        except ValueError:
            logger.exception("Review analysis failed due to invalid JSON output")
            send_telegram_message(
                "⚠️ Review analysis failed today — could not parse model output."
            )
            return 1

        r = get_redis_client()
        save_digest(r, date_str, topics, reviews)

        digest_message = build_digest_text(package_name, date_str, len(reviews), topics)
        send_telegram_message(digest_message)
        logger.info("Worker completed successfully")
        return 0
    except Exception:
        logger.exception("Worker failed unexpectedly")
        return 1


if __name__ == "__main__":
    sys.exit(main())
