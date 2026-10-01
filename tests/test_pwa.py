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
def test_icons_are_valid_png(size):
    width, height, raw = decode_png(pwa.icon(size))
    assert (width, height) == (size, size)
    assert len(raw) == size * (1 + 3 * size)  # one filter byte + RGB per row
    assert b"\xff\xff\xff" in raw and b"\x2f\x6f\xde" in raw  # rings on accent
    with pytest.raises(ValueError):
        pwa.icon(64)


def test_manifest_and_head():
    manifest = json.loads(pwa.manifest())
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/offers"
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
