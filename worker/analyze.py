import json
import logging
import os
import re
import time

import ollama

logger = logging.getLogger(__name__)

client = ollama.Client(host=os.environ["OLLAMA_HOST"])
MODEL = os.environ["OLLAMA_MODEL"].strip().strip("\"'")
MAX_RETRIES = 3
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "20"))
NUM_CONTEXT = int(os.environ.get("NUM_CONTEXT", "8192"))

DEFAULT_CATEGORIZE_PROMPT = """You are an analyst for a mobile game. You receive a numbered list of user reviews.

Task:
- For each review, extract the main complaint and assign a concise topic name.
- If the review is not a complaint, set the topic to "Undefined".

Rules:
- Keep the same order and numbering as the input.
- Topic names must be concise (2-5 words, Title Case).
- Return ONLY a numbered list of complaint topics, one per review.
- No extra text, no JSON, no explanations.

Example output format:
1. Game Crashes on Launch
2. Undefined
3. Unfair Matchmaking"""

DEFAULT_NORMALIZE_TOPIC_PROMPT = """You are an analyst for a mobile game. You receive a numbered list in the format:
1. <topic> | <complaint>
2. <topic> | <complaint>
...

Task:
- Group reviews with similar complaints into unified topics.
- Normalize topic names to be concise (2-5 words, Title Case).
- Return ONLY a numbered list of the final topic for each review, in the same order as input.
- No extra text, no JSON, no explanations.

Example output format:
1. Game Crashes on Launch
2. Too Many Ads
3. Game Crashes on Launch"""

CATEGORIZE_PROMPT = os.environ.get("BATCH_CATEGORIZE_PROMPT", DEFAULT_CATEGORIZE_PROMPT)
NORMALIZE_TOPIC_PROMPT = os.environ.get(
    "BATCH_NORMALIZE_TOPIC_PROMPT", DEFAULT_NORMALIZE_TOPIC_PROMPT
)


def _get_response_from_ollama(
    user_message: str,
    system_prompt: str,
    num_context: int = NUM_CONTEXT,
    response_format: str | None = None,
) -> str:
    content_buffer = ""
    thinking_buffer = ""

    chat_args = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "options": {"num_ctx": num_context},
        "stream": True,
    }
    if response_format:
        chat_args["format"] = response_format

    for chunk in client.chat(**chat_args):
        content_buffer += chunk.get("message", {}).get("content") or ""
        thinking_buffer += chunk.get("message", {}).get("thinking") or ""
        if len(thinking_buffer) > NUM_CONTEXT:
            logger.info(thinking_buffer)
            thinking_buffer = ""

    logger.info(thinking_buffer)
    logger.info("Content buffer: %s", content_buffer)

    # not used!
    if response_format == "json":
        try:
            parsed = json.loads(content_buffer)
            logger.info("Received complete JSON response from Ollama")
            return json.dumps(parsed)
        except json.JSONDecodeError:
            logger.error(
                "Failed to parse JSON response from Ollama: %s", content_buffer
            )

    return content_buffer


def _parse_numbered_topics(raw: str) -> dict[int, str]:
    topics: dict[int, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(\d+)\s*[\.)]\s*(.+)$", stripped)
        if not match:
            continue
        index = int(match.group(1))
        value = match.group(2).strip()
        if not value:
            continue
        if "|" in value:
            value = value.split("|", 1)[0].strip()
        topics[index] = value
    return topics


def _categorize_reviews(
    reviews: list[dict],
    index_offset: int,
    user_message: str,
) -> dict[int, str]:
    categorized_topics: dict[int, str] | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Categorize batch of %s reviews (attempt %s/%s)",
                len(reviews),
                attempt,
                MAX_RETRIES,
            )
            logger.info("User message to Ollama:\n%s", user_message)

            raw_response = _get_response_from_ollama(
                user_message,
                system_prompt=CATEGORIZE_PROMPT,
                num_context=(NUM_CONTEXT * 0.5 * attempt),
            )

            if not raw_response.strip():
                raise ValueError("Ollama returned empty categorize content")

            logger.info("Ollama categorize raw response: %s", raw_response)

            categorized_topics = _parse_numbered_topics(raw_response)
            if not categorized_topics:
                raise ValueError("Ollama returned no categorized topics")
            break
        except ValueError as exc:
            if attempt == MAX_RETRIES:
                logger.warning(
                    "Categorize failed after %s attempts: %s", MAX_RETRIES, exc
                )
                break
            logger.warning(
                "Categorize output invalid (attempt %s/%s): %s",
                attempt,
                MAX_RETRIES,
                exc,
            )
            time.sleep(2)
        except (ollama.ResponseError, Exception) as exc:
            if attempt == MAX_RETRIES:
                logger.warning(
                    "Categorize chat failed after %s attempts: %s", MAX_RETRIES, exc
                )
                break
            logger.warning(
                "Categorize chat failed (attempt %s/%s): %s", attempt, MAX_RETRIES, exc
            )
            time.sleep(5)

    if categorized_topics is None:
        categorized_topics = {}
        for idx in range(1, len(reviews) + 1):
            review_number = idx + index_offset
            categorized_topics[review_number] = "Undefined"

    return categorized_topics


def _build_topic_review_lines(
    reviews: list[dict],
    index_offset: int,
    categorized_topics: dict[int, str],
) -> list[str]:
    numbered_topic_reviews: list[str] = []
    for idx, review in enumerate(reviews, start=1):
        review_number = idx + index_offset
        topic = categorized_topics.get(review_number, "Undefined")
        review_text = review.get("text", "")
        numbered_topic_reviews.append(f"{review_number}. {topic} | {review_text}")
    return numbered_topic_reviews


def _normalize_topics(
    reviews: list[dict],
    normalize_message: str,
    categorized_topics: dict[int, str],
) -> dict[int, str]:
    normalized_topics: dict[int, str] | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Normalize batch of %s reviews (attempt %s/%s)",
                len(reviews),
                attempt,
                MAX_RETRIES,
            )
            normalized_raw = _get_response_from_ollama(
                normalize_message,
                system_prompt=NORMALIZE_TOPIC_PROMPT,
                num_context=(NUM_CONTEXT * 0.5 * attempt),
            )
            if not normalized_raw.strip():
                raise ValueError("Ollama returned empty normalize content")
            logger.info("Ollama normalize raw response: %s", normalized_raw)

            normalized_topics = _parse_numbered_topics(normalized_raw)
            if not normalized_topics:
                raise ValueError("Ollama returned no normalized topics")
            break
        except ValueError as exc:
            if attempt == MAX_RETRIES:
                logger.warning(
                    "Normalize failed after %s attempts: %s", MAX_RETRIES, exc
                )
                break
            logger.warning(
                "Normalize output invalid (attempt %s/%s): %s",
                attempt,
                MAX_RETRIES,
                exc,
            )
            time.sleep(2)
        except (ollama.ResponseError, Exception) as exc:
            if attempt == MAX_RETRIES:
                logger.warning(
                    "Normalize chat failed after %s attempts: %s", MAX_RETRIES, exc
                )
                break
            logger.warning(
                "Normalize chat failed (attempt %s/%s): %s", attempt, MAX_RETRIES, exc
            )
            time.sleep(5)

    if normalized_topics is None:
        normalized_topics = categorized_topics

    return normalized_topics


def _aggregate_topics(
    reviews: list[dict],
    index_offset: int,
    normalized_topics: dict[int, str],
) -> list[dict]:
    aggregated: dict[str, dict] = {}
    for idx in range(1, len(reviews) + 1):
        review_number = idx + index_offset
        topic = normalized_topics.get(review_number, "Undefined")
        if not topic:
            topic = "Undefined"
        entry = aggregated.setdefault(
            topic, {"topic": topic, "count": 0, "review_indices": []}
        )
        entry["count"] += 1
        entry["review_indices"].append(review_number)

    return list(aggregated.values())


def _analyze_batch(reviews: list[dict], index_offset: int) -> list[dict]:
    numbered_reviews = [
        f"{idx + index_offset}. {review.get('text', '')}"
        for idx, review in enumerate(reviews, start=1)
    ]
    user_message = "\n".join(numbered_reviews)

    categorized_topics = _categorize_reviews(
        reviews, index_offset=index_offset, user_message=user_message
    )
    numbered_topic_reviews = _build_topic_review_lines(
        reviews, index_offset=index_offset, categorized_topics=categorized_topics
    )
    normalize_message = "\n".join(numbered_topic_reviews)
    normalized_topics = _normalize_topics(
        reviews,
        normalize_message=normalize_message,
        categorized_topics=categorized_topics,
    )
    return _aggregate_topics(
        reviews, index_offset=index_offset, normalized_topics=normalized_topics
    )


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
