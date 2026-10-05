import httpx
import pytest

from intern_radar.models import Company
from intern_radar.sources.base import (
    SourceError,
    get_json,
    html_to_text,
    iso_date,
    require_param,
)
from tests.factories import mock_client


def test_html_to_text_handles_escaped_markup():
    markup = "&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;"
    assert html_to_text(markup) == "About\nBuild & ship"


def test_html_to_text_keeps_list_items_on_their_own_lines():
    markup = "<ul><li>Python</li><li>PyTorch</li></ul>Start:&nbsp;March<br/>2027"
    assert html_to_text(markup) == "Python\nPyTorch\nStart: March\n2027"


def test_iso_date():
    assert iso_date("2026-09-17T13:05:33-04:00") == "2026-09-17"
    assert iso_date(None) is None
    assert iso_date("") is None


def test_require_param():
    company = Company("Acme", "A", "greenhouse", {"board": "acme"})
    assert require_param(company, "board") == "acme"
    with pytest.raises(SourceError, match="Acme: missing 'site'"):
        require_param(company, "site")


def test_get_json_wraps_http_errors():
    client = mock_client({"GET https://api.example/ok": {"a": 1}})
    assert get_json(client, "GET", "https://api.example/ok") == {"a": 1}
    with pytest.raises(SourceError, match="404"):
        get_json(client, "GET", "https://api.example/missing")


def test_get_json_errors_do_not_leak_query_parameters():
    client = mock_client({})
    with pytest.raises(SourceError) as info:
        get_json(client, "GET", "https://api.example/x", params={"app_key": "SECRET"})
    assert "SECRET" not in str(info.value)
    assert "404" in str(info.value)


def test_get_json_retries_transient_errors(monkeypatch):
    from intern_radar.sources import base

    waits = []
    monkeypatch.setattr(base, "retry_sleep", waits.append)
    answers = iter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = mock_client(
        {"GET https://api.example/busy": lambda request: next(answers)}
    )
    assert get_json(client, "GET", "https://api.example/busy") == {"ok": True}
    assert waits == [7.0, 10.0]  # Retry-After honoured, then the default backoff


def test_get_json_gives_up_after_the_retries(monkeypatch):
    from intern_radar.sources import base

    waits = []
    monkeypatch.setattr(base, "retry_sleep", waits.append)
    client = mock_client({"GET https://api.example/down": 503})
    with pytest.raises(SourceError, match="503"):
        get_json(client, "GET", "https://api.example/down")
    assert waits == [3.0, 10.0]
    huge = httpx.Response(429, headers={"Retry-After": "3600"})
    assert base._delay(huge, 3.0) == base.MAX_RETRY_AFTER
    assert base._delay(httpx.Response(429, headers={"Retry-After": "soon"}), 3.0) == 3.0


def test_get_json_does_not_retry_client_errors(monkeypatch):
    from intern_radar.sources import base

    waits = []
    monkeypatch.setattr(base, "retry_sleep", waits.append)
    with pytest.raises(SourceError, match="404"):
        get_json(mock_client({}), "GET", "https://api.example/missing")
    assert waits == []
