"""Installable web app: manifest, icons and an offline-reading service worker.

The icons are the project's logo mark (radar and briefcase) on its navy
background, stored as PNG files in `static/`. The service worker only
registers in a secure context (HTTPS, e.g. `tailscale serve`); over plain
HTTP the manifest and the apple-touch-icon still make the page installable
on the home screen.
"""

import json
from functools import cache
from pathlib import Path

ICON_SIZES = (180, 192, 512)
STATIC = Path(__file__).parent / "static"
# The logo's navy: status bar, splash screen and icon background match.
THEME = "#051123"
BACKGROUND = "#051123"
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


@cache
def icon(size: int) -> bytes:
    """The app icon as PNG: the logo mark, kept inside the maskable safe zone."""
    if size not in ICON_SIZES:
        raise ValueError(size)
    return (STATIC / f"icon-{size}.png").read_bytes()
