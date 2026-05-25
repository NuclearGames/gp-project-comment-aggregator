import json
import logging
import os

from google.cloud import translate_v2
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


class GoogleTranslator:
    """Translate text to English using Google Cloud Translate."""

    def __init__(self, target_language: str = "en") -> None:
        self.target_language = target_language
        self.client = self._build_client()

    def translate(self, text: str, source_language: str | None) -> str:
        if not text:
            return text
        if not source_language or source_language == self.target_language:
            return text
        try:
            response = self.client.translate(
                text,
                target_language=self.target_language,
                source_language=source_language,
                format_="text",
            )
            return response.get("translatedText", text)
        except Exception as exc:
            logger.exception("Translate failed for lang=%s: %s", source_language, exc)
            return text

    def _build_client(self) -> translate_v2.Client:
        service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if service_account_json:
            info = json.loads(service_account_json)
            credentials = service_account.Credentials.from_service_account_info(info)
            project_id = info.get("project_id")
        else:
            credentials = service_account.Credentials.from_service_account_file(
                os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_PATH"]
            )
            project_id = None
        if project_id:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        return translate_v2.Client(credentials=credentials)
