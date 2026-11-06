"""Recorded HTTP answers of the real job boards, replayed offline in the tests.

`scripts/record_cassettes.py` runs each source adapter once against its
real API through `RecordingTransport` and saves every request and answer in
`tests/cassettes/<adapter>.json`, with the jobs the adapter produced. The
tests replay the file through `ReplayTransport` and check that the adapter
still produces the same jobs: a parser change that breaks on the real
payload shape fails in CI, without any network call.

Secrets (Adzuna's `app_id` / `app_key`) are replaced before writing, and
long listings are cut so that a cassette stays small.
"""

import json
from datetime import date
from typing import Any

import httpx

from intern_radar.models import Company, Job
from intern_radar.prefilter import ListingRules
from intern_radar.sources.adzuna import AdzunaSource
from intern_radar.sources.amazon import AmazonSource
from intern_radar.sources.ashby import AshbySource
from intern_radar.sources.base import Source
from intern_radar.sources.greenhouse import GreenhouseSource
from intern_radar.sources.lever import LeverSource
from intern_radar.sources.microsoft import MicrosoftSource
from intern_radar.sources.simplify import SimplifySource
from intern_radar.sources.smartrecruiters import SmartRecruitersSource
from intern_radar.sources.teamtailor import TeamtailorSource
from intern_radar.sources.workable import WorkableSource
from intern_radar.sources.workday import WorkdaySource

SECRET_PARAMS = ("app_id", "app_key")
REDACTED = "REDACTED"
MAX_ITEMS = 12  # items kept in a long listing
MAX_TEXT = 1500  # characters kept in a long text field


def scrub(url: httpx.URL) -> str:
    """The URL with secret query parameters replaced and parameters sorted."""
    params = sorted(
        (key, REDACTED if key in SECRET_PARAMS else value)
        for key, value in url.params.multi_items()
    )
    return str(url.copy_with(params=params))


def request_key(method: str, url: str, body: str) -> str:
    return f"{method} {url} {body}"


class RecordingTransport(httpx.BaseTransport):
    """Sends requests for real and keeps every exchange."""

    def __init__(self, inner: httpx.BaseTransport | None = None) -> None:
        self._inner = inner or httpx.HTTPTransport()
        self.exchanges: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        response.read()
        self.exchanges.append(
            {
                "method": request.method,
                "url": scrub(request.url),
                "body": request.content.decode() if request.content else "",
                "status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "text": response.text,
            }
        )
        # `content` is already decoded: drop the headers describing the
        # compressed body, or the client would decode it a second time.
        headers = [
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in ("content-encoding", "content-length")
        ]
        return httpx.Response(
            response.status_code, headers=headers, content=response.content,
            request=request,
        )  # fmt: skip


class ReplayTransport(httpx.BaseTransport):
    """Answers from recorded exchanges; an unrecorded request is an error."""

    def __init__(self, exchanges: list[dict[str, Any]]) -> None:
        self._answers = {
            request_key(e["method"], e["url"], e["body"]): e for e in exchanges
        }

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode() if request.content else ""
        key = request_key(request.method, scrub(request.url), body)
        exchange = self._answers.get(key)
        if exchange is None:
            raise AssertionError(f"request not in the cassette: {key}")
        return httpx.Response(
            exchange["status"],
            headers={"content-type": exchange["content_type"]},
            content=exchange["text"].encode(),
            request=request,
        )


def _shorten(value: Any, keep: tuple[str, ...]) -> Any:
    """Long lists cut to MAX_ITEMS, long strings to MAX_TEXT, recursively.

    Items of a long list containing one of the `keep` strings (the URLs of
    the jobs the adapter produced) come first, so that the cut listing still
    yields jobs, then a few others for the adapter's filters to reject.
    """
    if isinstance(value, list):
        if len(value) > MAX_ITEMS:
            wanted = [item for item in value if _contains(item, keep)]
            others = [item for item in value if not _contains(item, keep)]
            value = wanted[: MAX_ITEMS - 4] + others[:4]
        return [_shorten(item, keep) for item in value]
    if isinstance(value, dict):
        return {key: _shorten(item, keep) for key, item in value.items()}
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT]
    return value


def _contains(item: Any, keep: tuple[str, ...]) -> bool:
    text = json.dumps(item, ensure_ascii=False)
    return any(needle in text for needle in keep)


def shorten(
    exchanges: list[dict[str, Any]], keep: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    """Exchanges with long JSON listings cut, so that a cassette stays small.

    The jobs expected from a cassette are computed after cutting, by
    replaying it: they always match what the tests will see.
    """
    short = []
    for exchange in exchanges:
        exchange = dict(exchange)
        # Some hosts serve JSON as text/plain (raw.githubusercontent.com).
        if exchange["text"].lstrip()[:1] in ("{", "["):
            try:
                data = json.loads(exchange["text"])
            except ValueError:
                pass
            else:
                exchange["text"] = json.dumps(_shorten(data, keep), ensure_ascii=False)
        short.append(exchange)
    return short


def build_source(
    adapter: str, client: httpx.Client, setup: dict[str, Any], secrets: dict[str, str]
) -> Source:
    """The adapter as the pipeline builds it, without the pre-filter rules
    (every internship-titled posting is fetched in full)."""
    lookup = {name: tuple(value) for name, value in setup.get("lookup", {}).items()}
    simple: dict[str, type] = {
        "greenhouse": GreenhouseSource,
        "lever": LeverSource,
        "ashby": AshbySource,
        "workable": WorkableSource,
        "smartrecruiters": SmartRecruitersSource,
        "teamtailor": TeamtailorSource,
        "workday": WorkdaySource,
        "amazon": AmazonSource,
        "microsoft": MicrosoftSource,
    }
    if adapter in simple:
        return simple[adapter](client)
    if adapter == "adzuna":
        return AdzunaSource(
            client,
            secrets.get("app_id", REDACTED),
            secrets.get("app_key", REDACTED),
            lookup,  # type: ignore[arg-type]
            setup["terms"],
        )
    if adapter == "simplify":
        window = (
            date.fromisoformat(setup["window"][0]),
            date.fromisoformat(setup["window"][1]),
        )
        rules: ListingRules | None = None
        return SimplifySource(client, lookup, window, rules)  # type: ignore[arg-type]
    raise ValueError(f"unknown adapter: {adapter}")


def company_of(data: dict[str, Any]) -> Company:
    return Company(data["name"], data["tier"], data["source"], data.get("params", {}))


def job_summary(job: Job) -> dict[str, Any]:
    """The fields a cassette checks for each job."""
    return {
        "id": job.id,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "url": job.url,
        "posted_at": job.posted_at,
        "description_chars": len(job.description or ""),
    }


def redact(exchanges: list[dict[str, Any]], secrets: list[str]) -> list[dict[str, Any]]:
    """Exchanges with every secret value replaced, in URLs and in answers
    (Adzuna repeats the app id in the links of its offers)."""
    values = [value for value in secrets if value]
    redacted = []
    for exchange in exchanges:
        exchange = dict(exchange)
        for value in values:
            exchange["url"] = exchange["url"].replace(value, REDACTED)
            exchange["text"] = exchange["text"].replace(value, REDACTED)
        redacted.append(exchange)
    return redacted
