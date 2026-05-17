import json

import redis

from shared.redis_store import (
    decode_redis_value,
    topic_slug,
)

TTL_SECONDS = 2_592_000  # 30 days in seconds


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
        slug = topic_slug(topic_name)
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


def list_topics(r: redis.Redis, date_str: str) -> list[str]:
    """List stored topic names for a given date.

    Args:
        r: Redis client instance.
        date_str: ISO-8601 date string used as the key prefix.

    Returns:
        List of topic name strings.
    """
    values = r.lrange(f"topics:{date_str}", 0, -1)
    return [decode_redis_value(v) for v in values]
