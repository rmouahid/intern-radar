"""Installable web app: manifest, icons and an offline-reading service worker.

Icons are drawn here as PNG with the standard library (no image dependency):
a radar — rings and a sweep — on the accent colour. The service worker only
registers in a secure context (HTTPS, e.g. `tailscale serve`); over plain
HTTP the manifest and the apple-touch-icon still make the page installable
on the home screen.
"""

import json
import math
import struct
import zlib
from functools import cache

ICON_SIZES = (180, 192, 512)
THEME = "#2f6fde"
BACKGROUND = "#f6f6f4"
CACHE_PAGES = 40  # pages kept for offline reading

HEAD = (
    '<link rel="manifest" href="/manifest.webmanifest">'
    f'<meta name="theme-color" content="{THEME}">'
    '<link rel="apple-touch-icon" href="/icon-180.png">'
    '<link rel="icon" type="image/png" href="/icon-192.png">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="Radar">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    "<script>if('serviceWorker' in navigator&&window.isSecureContext)"
    "navigator.serviceWorker.register('/sw.js');"
    # Copy buttons (data-copy="<element id>"); the textarea fallback also works
    # over plain HTTP and on iPhone Safari, where the clipboard API is off.
    "document.addEventListener('click',function(ev){"
    "var b=ev.target.closest('[data-copy]');if(!b)return;ev.preventDefault();"
    "var s=document.getElementById(b.dataset.copy);if(!s)return;"
    "var t=s.value!==undefined?s.value:s.innerText;"
    "function ok(){var l=b.textContent;b.textContent='✓ Copié';"
    "setTimeout(function(){b.textContent=l},1500)}"
    "if(navigator.clipboard&&window.isSecureContext){"
    "navigator.clipboard.writeText(t).then(ok);return}"
    "var a=document.createElement('textarea');a.value=t;"
    "a.setAttribute('readonly','');a.style.position='fixed';a.style.opacity='0';"
    "document.body.appendChild(a);a.select();a.setSelectionRange(0,t.length);"
    "try{document.execCommand('copy');ok()}catch(e){}document.body.removeChild(a)"
    "})</script>"
)


def manifest() -> str:
    return json.dumps(
        {
            "name": "intern-radar",
            "short_name": "Radar",
            "description": "Offres de stage IA, candidatures et statistiques",
            "lang": "fr",
            "start_url": "/offers",
            "scope": "/",
            "display": "standalone",
            "background_color": BACKGROUND,
            "theme_color": THEME,
            "icons": [
                {
                    "src": f"/icon-{size}.png",
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                    "purpose": "any maskable" if size == 512 else "any",
                }
                for size in ICON_SIZES
            ],
        },
        ensure_ascii=False,
    )


SERVICE_WORKER = """// intern-radar: keeps the last pages for offline reading.
const CACHE = 'radar-pages-v1';
const LIMIT = __LIMIT__;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE)
        .map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function remember(request, response) {
  const cache = await caches.open(CACHE);
  await cache.put(request, response);
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - LIMIT))) {
    await cache.delete(key);
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET' || request.mode !== 'navigate') return;
  // Network first: fresh data when online, the last copy when offline.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) event.waitUntil(remember(request, response.clone()));
        return response;
      })
      .catch(async () => (await caches.match(request)) || new Response(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" ' +
        'content="width=device-width"><body style="font-family:sans-serif;' +
        'padding:24px"><h1>Hors ligne</h1><p>Cette page n\\'a pas encore été ' +
        'consultée : reconnecte-toi à Tailscale pour la charger.</p>',
        {headers: {'Content-Type': 'text/html; charset=utf-8'}}
      ))
  );
});
""".replace("__LIMIT__", str(CACHE_PAGES))


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + row for row in rows)  # filter 0 on every row
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


@cache
def icon(size: int) -> bytes:
    """The app icon as PNG: rings, a sweep and a blip on the accent colour."""
    if size not in ICON_SIZES:
        raise ValueError(size)
    background = (0x2F, 0x6F, 0xDE)
    light = (0xFF, 0xFF, 0xFF)
    sweep_colour = (0x9B, 0xB8, 0xEF)
    centre = (size - 1) / 2
    radius = size * 0.36  # inside the maskable safe zone
    line = max(1.5, size / 64)
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx, dy = x - centre, centre - y
            distance = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(dy, dx)) % 360
            colour = background
            if distance <= radius and 20 <= angle <= 75:
                colour = sweep_colour  # the sweep sector
            for ring in (radius, radius * 0.66, radius * 0.33):
                if abs(distance - ring) <= line / 2:
                    colour = light
            if distance <= line * 1.2:
                colour = light  # centre
            blip = math.hypot(dx - radius * 0.3, dy - radius * 0.42)
            if blip <= line * 2.2:
                colour = light
            row += bytes(colour)
        rows.append(bytes(row))
    return _png(size, size, rows)
