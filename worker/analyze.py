import json
import logging
import os
import re
import time

import ollama

logger = logging.getLogger(__name__)

client = ollama.Client(host=os.environ["OLLAMA_HOST"])
MODEL = os.environ["OLLAMA_MODEL"]
MAX_RETRIES = 3
BATCH_SIZE = 20

DEFAULT_SYSTEM_PROMPT = """You are an analyst for a mobile game. You receive a list of user reviews.
Your task is to group them into complaint topics.

Rules:
- Focus only on complaints and negative feedback. Ignore purely positive reviews.
- Each review may belong to only one topic (the most relevant one).
- Topic names must be concise (2–5 words, title case), e.g. "Game Crashes on Launch",
  "Too Many Ads", "Unfair Matchmaking".
- Sort topics by count descending.
- Return ONLY valid JSON — no markdown fences, no explanation, no preamble — in this
  exact schema:
  [
    {
      "topic": "<topic name>",
      "count": <number of reviews>,
      "review_indices": [<1-based indices of matching reviews>]
    }
  ]
  If there are no complaints at all, return an empty JSON array: []"""

SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)


def _parse_json_safe(raw: str) -> list | dict:
    """Parse JSON from the model output and raise on invalid JSON.

    Args:
        raw: Raw response string from the model.

    Returns:
        Parsed JSON value, expected to be a list.

    Raises:
        ValueError: If the response is not valid JSON.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Ollama response: %s\nRaw: %s", e, raw)
        raise ValueError(f"Ollama returned non-JSON output: {e}") from e


def _normalize_topics(payload: list | dict) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("topics", "results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if len(payload) == 1:
            value = next(iter(payload.values()))
            if isinstance(value, list):
                return value
    raise ValueError("Ollama returned JSON that is not a list")


def _analyze_batch(reviews: list[dict], index_offset: int) -> list[dict]:
    numbered_reviews = [
        f"{idx + index_offset}. {review.get('text', '')}"
        for idx, review in enumerate(reviews, start=1)
    ]
    user_message = "\n".join(numbered_reviews)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:

            logger.info(
                "Sending batch of %s reviews to Ollama (attempt %s/%s)",
                len(reviews),
                attempt,
                MAX_RETRIES,
            )
            logger.info("User message to Ollama:\n%s", user_message)

            response = client.chat(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                format="json",
                options={"temperature": 0.1},
            )
            raw = response["message"]["content"]

            logger.info("Ollama raw response: %s", raw)

            parsed = _parse_json_safe(raw)
            return _normalize_topics(parsed)
        except ValueError:
            raise
        except (ollama.ResponseError, Exception) as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            logger.warning(
                "Ollama chat failed (attempt %s/%s): %s", attempt, MAX_RETRIES, exc
            )
            time.sleep(5)

    raise RuntimeError(
        f"Ollama analysis failed after {MAX_RETRIES} retries: {last_error}"
    ) from last_error


def analyze_reviews(reviews: list[dict]) -> list[dict]:
    """Analyze reviews and group complaints into topic buckets.

    Args:
        reviews: List of review dictionaries with text fields.

    Returns:
        List of topic dictionaries with counts and review indices.

    Raises:
        RuntimeError: If analysis fails after retries.
        ValueError: If the model returns invalid JSON.
    """
    if not reviews:
        return []

    aggregated: dict[str, dict] = {}

    for start in range(0, len(reviews), BATCH_SIZE):
        batch = reviews[start : start + BATCH_SIZE]
        batch_results = _analyze_batch(batch, index_offset=start)

        for item in batch_results:
            topic = item.get("topic")
            if not topic:
                continue
            entry = aggregated.setdefault(
                topic, {"topic": topic, "count": 0, "review_indices": []}
            )
            entry["count"] += int(item.get("count", 0))
            entry["review_indices"].extend(item.get("review_indices", []))

    results = list(aggregated.values())
    results.sort(key=lambda item: item.get("count", 0), reverse=True)
    return results
