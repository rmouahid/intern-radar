"""Pieces shared by the source plugins."""

import html
import logging
import re
from collections.abc import Callable, Container, Iterable
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

from intern_radar.models import Company, Job

log = logging.getLogger(__name__)


class SourceError(Exception):
    """A source could not be fetched or parsed."""


class Source(Protocol):
    def fetch(self, company: Company, known_ids: Container[str]) -> list[Job]:
        """Return the company's internship-titled jobs not in `known_ids`."""
        ...


BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Plain text from HTML, including entity-escaped HTML (Greenhouse)."""
    if "&lt;" in markup:
        markup = html.unescape(markup)
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = re.sub(r"[ \t\xa0]+", " ", "".join(parser.parts))
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def iso_date(value: str | None) -> str | None:
    return value[:10] if value else None


def require_param(company: Company, key: str) -> str:
    value = company.params.get(key)
    if not value:
        raise SourceError(f"{company.name}: missing '{key}' in companies.yaml")
    return str(value)


def get_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    try:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        # The message names the base URL only: query strings may hold API keys.
        status = exc.response.status_code
        raise SourceError(f"{method} {url}: HTTP {status}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError(f"{method} {url}: {type(exc).__name__}") from exc


# Errors raised by one malformed posting or one failed detail request.
SKIPPABLE = (KeyError, TypeError, AttributeError, ValueError, SourceError)


def collect(
    company: Company, items: Iterable[Any], convert: Callable[[Any], Job | None]
) -> list[Job]:
    """Convert each posting, skipping (and logging) the ones that fail.

    One broken posting must not hide the company's other offers; skipped
    postings are not stored, so they are retried on the next run.
    """
    jobs = []
    for item in items:
        try:
            job = convert(item)
        except SKIPPABLE as exc:
            log.warning(
                "%s: skipped a posting (%s: %s)", company.name, type(exc).__name__, exc
            )
            continue
        if job is not None:
            jobs.append(job)
    return jobs
