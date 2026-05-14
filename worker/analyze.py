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

SYSTEM_PROMPT = """You are an analyst for a mobile game. You receive a list of user reviews.
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


def _parse_json_safe(raw: str) -> list:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Ollama response: %s\nRaw: %s", e, raw)
        raise ValueError(f"Ollama returned non-JSON output: {e}") from e


def analyze_reviews(reviews: list[dict]) -> list[dict]:
    if not reviews:
        return []

    numbered_reviews = [f"{idx}. {review.get('text', '')}" for idx, review in enumerate(reviews, start=1)]
    user_message = "\n".join(numbered_reviews)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
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
            parsed = _parse_json_safe(raw)
            if not isinstance(parsed, list):
                raise ValueError("Ollama returned JSON that is not a list")
            return parsed
        except ValueError:
            raise
        except (ollama.ResponseError, Exception) as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            logger.warning("Ollama chat failed (attempt %s/%s): %s", attempt, MAX_RETRIES, exc)
            time.sleep(5)

    raise RuntimeError(f"Ollama analysis failed after {MAX_RETRIES} retries: {last_error}") from last_error
