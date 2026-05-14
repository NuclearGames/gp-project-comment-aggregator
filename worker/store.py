import json
import os

import redis

TTL_SECONDS = 2_592_000


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


def _topic_slug(topic_name: str) -> str:
    return topic_name.lower().replace(" ", "_")


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def save_digest(r: redis.Redis, date_str: str, topics: list[dict], reviews: list[dict]) -> None:
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
    value = r.get(f"digest:{date_str}")
    if value is None:
        return None
    return json.loads(_decode(value))


def get_reviews_for_topic(
    r: redis.Redis, date_str: str, topic_name: str, start: int, end: int
) -> list[str]:
    key = f"reviews:{date_str}:{_topic_slug(topic_name)}"
    values = r.lrange(key, start - 1, end - 1)
    return [_decode(v) for v in values]


def list_topics(r: redis.Redis, date_str: str) -> list[str]:
    values = r.lrange(f"topics:{date_str}", 0, -1)
    return [_decode(v) for v in values]
