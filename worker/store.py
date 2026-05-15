import json
import os

import redis

TTL_SECONDS = 2_592_000  # 30 days in seconds


def get_redis_client() -> redis.Redis:
    """Create a Redis client using the configured URL.

    Args:
        None.

    Returns:
        Redis client configured with decoded string responses.
    """
    return redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


def _topic_slug(topic_name: str) -> str:
    """Build a Redis-safe slug for a topic name.

    Args:
        topic_name: Human-readable topic name.

    Returns:
        Lowercased topic name with spaces replaced by underscores.
    """
    return topic_name.lower().replace(" ", "_")


def _decode(value):
    """Decode Redis byte values to strings.

    Args:
        value: Redis value that may be bytes or string.

    Returns:
        Decoded string value.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def save_digest(
    r: redis.Redis, date_str: str, topics: list[dict], reviews: list[dict]
) -> None:
    """Persist digest topics and per-topic reviews in Redis.

    Args:
        r: Redis client instance.
        date_str: ISO-8601 date string used as the key prefix.
        topics: List of topic summary dictionaries.
        reviews: List of raw review dictionaries.

    Returns:
        None.
    """
    digest_key = f"digest:{date_str}"
    topics_key = f"topics:{date_str}"

    r.set(digest_key, json.dumps(topics))
    r.expire(digest_key, TTL_SECONDS)

    r.delete(topics_key)
    if topics:
        r.rpush(topics_key, *[topic.get("topic", "") for topic in topics])
    r.expire(topics_key, TTL_SECONDS)

    for topic in topics:
        topic_name = topic.get("topic", "")
        slug = _topic_slug(topic_name)
        topic_reviews_key = f"reviews:{date_str}:{slug}"

        r.delete(topic_reviews_key)
        review_payloads = []
        for review_index in topic.get("review_indices", []):
            idx = int(review_index) - 1
            if idx < 0 or idx >= len(reviews):
                continue
            review = reviews[idx]
            review_payloads.append(
                json.dumps(
                    {
                        "author": review.get("author", "Unknown"),
                        "rating": int(review.get("rating", 0)),
                        "text": review.get("text", ""),
                        "date": review.get("date", ""),
                    }
                )
            )

        if review_payloads:
            r.rpush(topic_reviews_key, *review_payloads)
        r.expire(topic_reviews_key, TTL_SECONDS)


def get_digest(r: redis.Redis, date_str: str) -> list[dict] | None:
    """Fetch the stored digest for a given date.

    Args:
        r: Redis client instance.
        date_str: ISO-8601 date string used as the digest key suffix.

    Returns:
        Parsed digest list if present, otherwise None.
    """
    value = r.get(f"digest:{date_str}")
    if value is None:
        return None
    return json.loads(_decode(value))


def get_reviews_for_topic(
    r: redis.Redis, date_str: str, topic_name: str, start: int, end: int
) -> list[str]:
    """Read a slice of serialized reviews for a topic.

    Args:
        r: Redis client instance.
        date_str: ISO-8601 date string used as the key prefix.
        topic_name: Human-readable topic name.
        start: 1-based inclusive start index.
        end: 1-based inclusive end index.

    Returns:
        List of serialized review JSON strings.
    """
    key = f"reviews:{date_str}:{_topic_slug(topic_name)}"
    values = r.lrange(key, start - 1, end - 1)
    return [_decode(v) for v in values]


def list_topics(r: redis.Redis, date_str: str) -> list[str]:
    """List stored topic names for a given date.

    Args:
        r: Redis client instance.
        date_str: ISO-8601 date string used as the key prefix.

    Returns:
        List of topic name strings.
    """
    values = r.lrange(f"topics:{date_str}", 0, -1)
    return [_decode(v) for v in values]
