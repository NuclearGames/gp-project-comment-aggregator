import json
import os

import redis


def topic_slug(topic_name: str) -> str:
    """Build a Redis-safe slug for a topic name.

    Args:
        topic_name: Human-readable topic name.

    Returns:
        Lowercased topic name with spaces replaced by underscores.
    """
    return topic_name.lower().replace(" ", "_")


def decode_redis_value(value: str | bytes) -> str:
    """Decode Redis byte values to strings.

    Args:
        value: Redis value that may be bytes or string.

    Returns:
        Decoded string value.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def get_redis_client() -> redis.Redis:
    """Create a Redis client using the configured URL.

    Args:
        None.

    Returns:
        Redis client configured with decoded string responses.
    """
    return redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


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
    return json.loads(decode_redis_value(value))


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
    key = f"reviews:{date_str}:{topic_slug(topic_name)}"
    values = r.lrange(key, start - 1, end - 1)
    return [decode_redis_value(v) for v in values]
