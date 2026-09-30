"""A small HTTP server for the dashboard (standard library only).

It is meant to listen on the server's Tailscale address only: the tailnet is
the access control, so there is no login and nothing is exposed publicly.
The data is read-only; the only action is `POST /run`, which asks systemd
to start the scheduled run and is accepted only from the page itself.
"""

import logging
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from intern_radar.dashboard import queries
from intern_radar.dashboard.render import page
from intern_radar.dashboard.runner import RunStatus

NOTICES = {
    "started": "Run lancé : les résultats apparaîtront à la fin (quelques minutes).",
    "busy": "Un run est déjà en cours.",
    "error": "systemd a refusé de lancer le run (voir les logs du serveur).",
}

log = logging.getLogger(__name__)


def tailscale_ip(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str | None:
    """The machine's Tailscale IPv4 address, or None when Tailscale is absent."""
    try:
        proc = runner(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    address = (proc.stdout or "").strip().splitlines()
    return address[0] if proc.returncode == 0 and address else None


def render_dashboard(
    db_path: str,
    thresholds: tuple[float, float],
    now: datetime,
    run: RunStatus | None = None,
    notice: str | None = None,
) -> str:
    db = queries.connect(db_path)
    try:
        return page(
            now,
            queries.kpis(db, now),
            queries.weekly_funnel(db, now),
            queries.score_histogram(db),
            thresholds,
            queries.sources(db),
            queries.applications(db),
            queries.llm_usage(db, now),
            run,
            notice,
        )
    finally:
        db.close()


def make_server(
    db_path: str,
    host: str,
    port: int,
    thresholds: tuple[float, float],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    status: Callable[[], RunStatus] | None = None,
    trigger: Callable[[], bool] | None = None,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path == "/healthz":
                self._reply(200, "text/plain; charset=utf-8", "ok")
            elif url.path in ("/", "/index.html"):
                notice = NOTICES.get((parse_qs(url.query).get("run") or [""])[0])
                try:
                    run = status() if status else None
                    body = render_dashboard(db_path, thresholds, clock(), run, notice)
                except Exception:
                    log.exception("dashboard rendering failed")
                    self._reply(500, "text/plain; charset=utf-8", "error")
                    return
                self._reply(200, "text/html; charset=utf-8", body)
            else:
                self._reply(404, "text/plain; charset=utf-8", "not found")

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if urlparse(self.path).path != "/run" or trigger is None:
                self._reply(404, "text/plain; charset=utf-8", "not found")
                return
            if not self._same_origin():
                self._reply(403, "text/plain; charset=utf-8", "forbidden")
                return
            if status is not None and status().running:
                outcome = "busy"
            else:
                outcome = "started" if trigger() else "error"
            self.send_response(303)
            self.send_header("Location", f"/?run={outcome}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _same_origin(self) -> bool:
            """The form must come from this page (Origin, else Referer)."""
            source = self.headers.get("Origin") or self.headers.get("Referer") or ""
            host = self.headers.get("Host") or ""
            return bool(host) and urlparse(source).netloc == host

        def _reply(self, code: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            log.debug("dashboard: " + format, *args)

    return ThreadingHTTPServer((host, port), Handler)
