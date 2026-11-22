"""A small HTTP server for the dashboard (standard library only).

It listens on a private address, normally Tailscale, without a login.
All dashboard requests require an allowed Host. POST routes can start a run,
update applications, searches, profile data, answers, feedback and evaluation
labels, and generate application documents. Forms require a same-origin
request, and the autofill API checks a token.
"""

import json
import logging
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
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


def tailscale_hosts(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[str, ...]:
    """Return the local node's Tailscale addresses and MagicDNS names."""
    try:
        proc = runner(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return ()
        status = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ()
    node = status.get("Self") if isinstance(status, dict) else None
    if not isinstance(node, dict):
        return ()
    ips = node.get("TailscaleIPs")
    addresses = (
        tuple(ip for ip in ips if isinstance(ip, str)) if isinstance(ips, list) else ()
    )
    dns_name = node.get("DNSName")
    name = dns_name.rstrip(".") if isinstance(dns_name, str) else ""
    return (*addresses, name, f"{name}.", name.partition(".")[0]) if name else addresses


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
    allowed_hosts: frozenset[str]

    def _serve(self, method: str) -> None:
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.allowed_hosts:
            self.send_error(HTTPStatus.MISDIRECTED_REQUEST)
            return
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
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ThreadingHTTPServer:
    ctx = context or Context(
        db_path, thresholds, clock=clock, status=status, trigger=trigger
    )
    names = {host, "localhost", "127.0.0.1", *tailscale_hosts()} - {"", "0.0.0.0"}
    handler = type("Handler", (_Handler,), {"app": build_app(ctx)})
    server = ThreadingHTTPServer((host, port), handler)
    bound_host, bound_port = server.server_address
    if bound_host != "0.0.0.0":
        names.add(bound_host)
    names = {f"[{name}]" if ":" in name else name for name in names}
    authorities = {f"{name}:{bound_port}" for name in names}
    if bound_port == 80:
        authorities.update(names)
    handler.allowed_hosts = frozenset(
        value.lower() for value in (*authorities, *allowed_hosts)
    )
    return server
