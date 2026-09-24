import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fpdf import FPDF

from intern_radar.letters.cv import CvError, CvSource, pdf_text
from tests.factories import mock_client

URL = "https://docs.example/cv/export"
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def make_pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 5, text)
    return bytes(pdf.output())


def pdf_route(text):
    return lambda request: httpx.Response(200, content=make_pdf(text))


def write_cache(path, age: timedelta, text: str) -> None:
    path.write_text(json.dumps({"fetched_at": (NOW - age).isoformat(), "text": text}))


def test_pdf_text_normalises_whitespace():
    data = make_pdf("RAYÂN   MOUAHID\nRAG  agent")
    assert pdf_text(data) == "RAYÂN MOUAHID\nRAG agent"


def test_downloads_and_caches(tmp_path):
    cache = tmp_path / "cv.json"
    client = mock_client({f"GET {URL}": pdf_route("RAG agent")})
    assert CvSource(client, URL, cache, clock=lambda: NOW).text() == "RAG agent"
    assert json.loads(cache.read_text())["text"] == "RAG agent"
    offline = CvSource(mock_client({}), URL, cache, clock=lambda: NOW)
    assert offline.text() == "RAG agent"


def test_stale_cache_is_used_when_download_fails(tmp_path):
    cache = tmp_path / "cv.json"
    write_cache(cache, timedelta(days=3), "old CV")
    source = CvSource(mock_client({}), URL, cache, clock=lambda: NOW)
    assert source.text() == "old CV"


def test_stale_cache_is_refreshed(tmp_path):
    cache = tmp_path / "cv.json"
    write_cache(cache, timedelta(days=3), "old CV")
    client = mock_client({f"GET {URL}": pdf_route("new CV")})
    assert CvSource(client, URL, cache, clock=lambda: NOW).text() == "new CV"


def test_no_cache_and_no_download_raises(tmp_path):
    source = CvSource(mock_client({}), URL, tmp_path / "cv.json", clock=lambda: NOW)
    with pytest.raises(CvError, match="CV"):
        source.text()
