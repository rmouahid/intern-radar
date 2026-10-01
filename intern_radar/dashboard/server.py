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

from intern_radar.dashboard.app import App, parse_request
from intern_radar.dashboard.routes import Context, build_app, render_stats
from intern_radar.dashboard.runner import RunStatus

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
    """The statistics page (kept for callers and tests)."""
    ctx = Context(
        db_path, thresholds, clock=lambda: now, status=(lambda: run) if run else None
    )
    return render_stats(ctx, notice)


class _Handler(BaseHTTPRequestHandler):
    app: App  # set on the subclass built by make_server

    def _serve(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        request = parse_request(method, self.path, dict(self.headers), body)
        response = self.app.handle(request)
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in response.headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response.body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self._serve("GET")

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        self._serve("POST")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        log.debug("dashboard: " + format, *args)


def make_server(
    db_path: str,
    host: str,
    port: int,
    thresholds: tuple[float, float],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    status: Callable[[], RunStatus] | None = None,
    trigger: Callable[[], bool] | None = None,
    context: Context | None = None,
) -> ThreadingHTTPServer:
    ctx = context or Context(
        db_path, thresholds, clock=clock, status=status, trigger=trigger
    )
    handler = type("Handler", (_Handler,), {"app": build_app(ctx)})
    return ThreadingHTTPServer((host, port), handler)
