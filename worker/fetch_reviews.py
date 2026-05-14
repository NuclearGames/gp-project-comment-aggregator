import logging
import os
from datetime import datetime, timezone, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)
SCOPE = "https://www.googleapis.com/auth/androidpublisher"


def _extract_user_comment(comments: list[dict]) -> dict | None:
    user_comments = [c.get("userComment", {}) for c in comments if c.get("userComment")]
    if not user_comments:
        return None
    return max(user_comments, key=lambda c: int(c.get("lastModified", {}).get("seconds", 0)))


def fetch_recent_reviews() -> list[dict]:
    credentials = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_PATH"], scopes=[SCOPE]
    )
    package_name = os.environ["PACKAGE_NAME"]
    lookback_hours = int(os.environ.get("LOOKBACK_HOURS", "24"))
    cutoff_seconds = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())

    service = build("androidpublisher", "v3", credentials=credentials, cache_discovery=False)

    results: list[dict] = []
    page_token = None

    while True:
        response = service.reviews().list(packageName=package_name, token=page_token).execute()
        for review in response.get("reviews", []):
            user_comment = _extract_user_comment(review.get("comments", []))
            if not user_comment:
                continue

            last_modified_seconds = int(user_comment.get("lastModified", {}).get("seconds", 0))
            if last_modified_seconds < cutoff_seconds:
                continue

            text = user_comment.get("text", "")
            results.append(
                {
                    "review_id": review.get("reviewId", ""),
                    "author": review.get("authorName", "Unknown"),
                    "rating": int(user_comment.get("starRating", 0)),
                    "text": text,
                    "date": datetime.fromtimestamp(last_modified_seconds, tz=timezone.utc)
                    .date()
                    .isoformat(),
                }
            )

        page_token = response.get("tokenPagination", {}).get("nextPageToken")
        if not page_token:
            break

    if not results:
        logger.warning("No reviews found in the last %s hours for package %s", lookback_hours, package_name)

    return results
