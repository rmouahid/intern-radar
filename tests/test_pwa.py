import io
import json
import struct
import zlib

import pytest

from intern_radar.dashboard import pwa
from intern_radar.dashboard.app import Request
from intern_radar.dashboard.routes import Context, build_app
from intern_radar.store import Store


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    stream, chunks = io.BytesIO(data[8:]), {}
    while True:
        length = struct.unpack(">I", stream.read(4))[0]
        kind = stream.read(4)
        body = stream.read(length)
        crc = struct.unpack(">I", stream.read(4))[0]
        assert crc == zlib.crc32(kind + body)
        chunks[kind] = chunks.get(kind, b"") + body
        if kind == b"IEND":
            break
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    return width, height, zlib.decompress(chunks[b"IDAT"])


@pytest.mark.parametrize("size", pwa.ICON_SIZES)
def test_icons_are_the_logo_mark_files(size):
    data = pwa.icon(size)
    assert data == (pwa.STATIC / f"icon-{size}.png").read_bytes()
    width, height, _ = decode_png(data)
    assert (width, height) == (size, size)
    with pytest.raises(ValueError):
        pwa.icon(64)


def test_manifest_and_head():
    manifest = json.loads(pwa.manifest())
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/offers"
    # The logo's navy, so the splash screen matches the icon background.
    assert manifest["theme_color"] == manifest["background_color"] == "#051123"
    assert [i["sizes"] for i in manifest["icons"]] == ["180x180", "192x192", "512x512"]
    assert 'rel="apple-touch-icon" href="/icon-180.png"' in pwa.HEAD
    assert "window.isSecureContext" in pwa.HEAD  # no registration over plain HTTP
    assert "const LIMIT = 40;" in pwa.SERVICE_WORKER


def test_pwa_routes(tmp_path):
    path = str(tmp_path / "p.db")
    Store(path).close()
    app = build_app(Context(path))
    manifest = app.handle(Request("GET", "/manifest.webmanifest", {}))
    assert manifest.content_type.startswith("application/manifest+json")
    worker = app.handle(Request("GET", "/sw.js", {}))
    assert worker.content_type.startswith("text/javascript")
    assert b"request.mode !== 'navigate'" in worker.body
    icon = app.handle(Request("GET", "/icon-192.png", {}))
    assert icon.content_type == "image/png" and icon.body == pwa.icon(192)
    assert app.handle(Request("GET", "/icon-64.png", {})).status == 404
    page = app.handle(Request("GET", "/offers", {})).body.decode()
    assert 'href="/manifest.webmanifest"' in page


def test_every_page_carries_the_brand_header(tmp_path):
    path = str(tmp_path / "p.db")
    Store(path).close()
    app = build_app(Context(path))
    for route in ("/offers", "/applications", "/stats"):
        body = app.handle(Request("GET", route, {})).body.decode()
        assert '<header class="brand">' in body
        assert 'src="/icon-192.png"' in body and "intern-<b>radar</b>" in body
