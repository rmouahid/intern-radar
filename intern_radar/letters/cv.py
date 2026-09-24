"""The candidate's CV text, read from its PDF export and cached."""

import io
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

log = logging.getLogger(__name__)


class CvError(Exception):
    """The CV could not be read."""


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


class CvSource:
    def __init__(
        self,
        client: httpx.Client,
        url: str,
        cache_path: Path,
        max_age: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._url = url
        self._cache_path = cache_path
        self._max_age = max_age
        self._clock = clock

    def text(self) -> str:
        cached = self._read_cache()
        now = self._clock()
        if cached and now - cached[0] < self._max_age:
            return cached[1]
        try:
            response = self._client.get(self._url)
            response.raise_for_status()
            text = pdf_text(response.content)
        except (httpx.HTTPError, PdfReadError, ValueError) as exc:
            if cached:
                log.warning("CV download failed, using cached copy: %s", exc)
                return cached[1]
            raise CvError(f"CV unavailable: {type(exc).__name__}") from exc
        if not text:
            raise CvError("CV PDF contains no text")
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps({"fetched_at": now.isoformat(), "text": text}),
            encoding="utf-8",
        )
        return text

    def _read_cache(self) -> tuple[datetime, str] | None:
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return datetime.fromisoformat(data["fetched_at"]), data["text"]
        except (OSError, ValueError, KeyError):
            return None
