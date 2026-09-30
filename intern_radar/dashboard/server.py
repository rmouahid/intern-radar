"""A small read-only HTTP server for the dashboard (standard library only).

It is meant to listen on the server's Tailscale address only: the tailnet is
the access control, so there is no login and nothing is exposed publicly.
"""

import logging
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from intern_radar.dashboard import queries
from intern_radar.dashboard.render import page

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
    db_path: str, thresholds: tuple[float, float], now: datetime
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
        )
    finally:
        db.close()


def make_server(
    db_path: str,
    host: str,
    port: int,
    thresholds: tuple[float, float],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path == "/healthz":
                self._reply(200, "text/plain; charset=utf-8", "ok")
            elif self.path in ("/", "/index.html"):
                try:
                    body = render_dashboard(db_path, thresholds, clock())
                except Exception:
                    log.exception("dashboard rendering failed")
                    self._reply(500, "text/plain; charset=utf-8", "error")
                    return
                self._reply(200, "text/html; charset=utf-8", body)
            else:
                self._reply(404, "text/plain; charset=utf-8", "not found")

        def _reply(self, status: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            log.debug("dashboard: " + format, *args)

    return ThreadingHTTPServer((host, port), Handler)
