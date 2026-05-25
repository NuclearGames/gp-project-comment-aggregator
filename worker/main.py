import logging
import os
import sys
from datetime import datetime, timezone

import requests
from analyze import analyze_reviews
from fetch_reviews import fetch_recent_reviews
from store import save_digest

from shared.digest import build_digest_text
from shared.redis_store import get_redis_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _assert_ollama_gpu() -> None:
    """Fail fast if the Ollama model is not running on GPU.

    Raises:
        RuntimeError: If the model is running on CPU or is not active.
    """
    host = os.environ["OLLAMA_HOST"].rstrip("/")
    raw_model = os.environ["OLLAMA_MODEL"]
    model = raw_model.strip().strip("\"'")
    response = requests.get(f"{host}/api/ps", timeout=10)
    response.raise_for_status()
    payload = response.json()

    def _check_processor(models: list[dict]) -> bool:
        for entry in models:
            name = entry.get("name") or entry.get("model")
            if isinstance(name, str) and name.lower() == model.lower():
                processor = str(entry.get("processor", "")).lower()
                if "cpu" in processor and not any(
                    token in processor for token in ("gpu", "cuda", "metal", "rocm")
                ):
                    raise RuntimeError(
                        "Ollama model '%s' is running on CPU (processor=%s)."
                        % (model, processor)
                    )
                return True
        return False

    if _check_processor(payload.get("models", [])):
        return

    warmup = requests.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": "ping",
            "stream": False,
            "options": {"num_predict": 1},
        },
        timeout=120,
    )
    try:
        warmup.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Ollama warmup failed for model '{model}': {warmup.text}"
        ) from exc

    response = requests.get(f"{host}/api/ps", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if _check_processor(payload.get("models", [])):
        return

    raise RuntimeError(
        f"Ollama model '{model}' not found in /api/ps after warmup. Is it running?"
    )


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
        json={"chat_id": chat_id, "text": text},
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

        logger.info("Worker started. Checking Ollama GPU status...")

        _assert_ollama_gpu()

        logger.info("Ollama GPU check passed. Fetching reviews and analyzing...")

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
