import json
import logging
import os
from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build
from translator import GoogleTranslator

logger = logging.getLogger(__name__)
SCOPE = "https://www.googleapis.com/auth/androidpublisher"


def _extract_user_comment(comments: list[dict]) -> dict | None:
    """Select the most recent user comment from a review thread.

    Args:
        comments: List of comment dictionaries from the API response.

    Returns:
        The most recent user comment dictionary, or None if not found.
    """
    user_comments = [c.get("userComment", {}) for c in comments if c.get("userComment")]
    if not user_comments:
        return None
    return max(
        user_comments, key=lambda c: int(c.get("lastModified", {}).get("seconds", 0))
    )


def fetch_recent_reviews() -> list[dict]:
    """Fetch recent Google Play reviews within the configured lookback window.

    Args:
        None.

    Returns:
        List of normalized review dictionaries.
    """
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if service_account_json:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(service_account_json), scopes=[SCOPE]
        )
    else:
        credentials = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_PATH"], scopes=[SCOPE]
        )
    package_name = os.environ["PACKAGE_NAME"]
    lookback_hours = int(os.environ.get("LOOKBACK_HOURS", "24"))
    cutoff_seconds = int(
        (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp()
    )

    service = build(
        "androidpublisher", "v3", credentials=credentials, cache_discovery=False
    )

    results: list[dict] = []
    page_token = None
    translator = GoogleTranslator()

    while True:
        try:
            response = (
                service.reviews()
                .list(packageName=package_name, token=page_token)
                .execute()
            )

            logger.info(
                "Fetched %d reviews from Google Play (page token: %s)",
                len(response.get("reviews", [])),
                page_token,
            )

            # logger.info("Response: %s", json.dumps(response, indent=2))

            for review in response.get("reviews", []):
                user_comment = _extract_user_comment(review.get("comments", []))
                if not user_comment:
                    continue

                last_modified_seconds = int(
                    user_comment.get("lastModified", {}).get("seconds", 0)
                )
                if last_modified_seconds < cutoff_seconds:
                    continue

                rating = int(user_comment.get("starRating", 0))
                if rating < 1 or rating > 3:
                    logger.info(
                        "Skipping review with rating %d (not a complaint): %s",
                        rating,
                        user_comment.get("text", ""),
                    )

                    continue

                text = user_comment.get("text", "")
                language = user_comment.get("reviewerLanguage", "")
                translated_text = translator.translate(text, language)
                results.append(
                    {
                        "review_id": review.get("reviewId", ""),
                        "author": review.get("authorName", "Unknown"),
                        "rating": rating,
                        "text": translated_text,
                        "date": datetime.fromtimestamp(
                            last_modified_seconds, tz=timezone.utc
                        )
                        .date()
                        .isoformat(),
                    }
                )

            page_token = response.get("tokenPagination", {}).get("nextPageToken")
            if not page_token:
                break
        except Exception as e:
            logger.exception("Error fetching reviews: %s", e)
            break

    if not results:
        logger.warning(
            "No reviews found in the last %s hours for package %s",
            lookback_hours,
            package_name,
        )

    return results
