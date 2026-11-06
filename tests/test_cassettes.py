"""Every source adapter replayed on a real answer of its job board.

The cassettes in tests/cassettes/ were recorded from the live APIs by
scripts/record_cassettes.py. Replaying them offline catches a parser change
that breaks on the real payload shape; re-record when a board changes its
API on purpose.
"""

import json
from pathlib import Path

import httpx
import pytest

from intern_radar.cassette import (
    REDACTED,
    ReplayTransport,
    build_source,
    company_of,
    job_summary,
    redact,
    scrub,
    shorten,
)
from intern_radar.http import Throttle, make_client
from intern_radar.sources import SOURCE_NAMES

CASSETTES = sorted((Path(__file__).parent / "cassettes").glob("*.json"))


def test_every_adapter_has_a_cassette():
    assert {path.stem for path in CASSETTES} == SOURCE_NAMES - {"none"}


@pytest.mark.parametrize("path", CASSETTES, ids=lambda path: path.stem)
def test_adapter_still_reads_its_recorded_answer(path):
    cassette = json.loads(path.read_text(encoding="utf-8"))
    transport = ReplayTransport(cassette["exchanges"])
    with make_client(Throttle(0), transport) as client:
        source = build_source(cassette["adapter"], client, cassette["setup"], {})
        jobs = source.fetch(company_of(cassette["company"]), set())
    assert [job_summary(job) for job in jobs] == cassette["expected"]
    for job in jobs:
        assert job.id.startswith(f"{job.source}:") or job.source == cassette["adapter"]
        assert job.url.startswith("http")
        assert job.title.strip()


def test_secrets_are_hidden_in_urls_and_answers():
    url = httpx.URL(
        "https://api.adzuna.com/v1/api/jobs/gb/search/1?app_key=k&what=ai&app_id=i"
    )
    assert scrub(url) == (
        f"https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id={REDACTED}"
        f"&app_key={REDACTED}&what=ai"
    )
    exchange = {
        "url": "https://x/?id=abc123",
        "text": "utm_source=abc123",
        "content_type": "",
    }
    assert redact([exchange], ["abc123"]) == [
        {
            "url": f"https://x/?id={REDACTED}",
            "text": f"utm_source={REDACTED}",
            "content_type": "",
        }
    ]


def test_long_listings_keep_the_wanted_items_first():
    items = [{"title": f"Engineer {n}", "url": f"https://x/{n}"} for n in range(50)]
    exchange = {
        "url": "u",
        "text": json.dumps({"jobs": items}),
        "content_type": "text/plain",
    }
    [short] = shorten([exchange], keep=("https://x/42",))
    kept = json.loads(short["text"])["jobs"]
    assert kept[0]["url"] == "https://x/42"
    assert len(kept) == 5  # the wanted item and four others


def test_a_request_missing_from_the_cassette_fails_loudly():
    with make_client(Throttle(0), ReplayTransport([])) as client:
        with pytest.raises(AssertionError, match="not in the cassette"):
            client.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs")
