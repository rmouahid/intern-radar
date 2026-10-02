"""A tiny web framework on top of http.server: requests, responses, routes.

Routes map a method and a path pattern (`/offers/<int:ref>`) to a handler
taking the request and the path parameters. POST requests are accepted only
when their Origin (or Referer) is the server itself; the server is reachable
on the Tailscale address only, so this is the whole access control.
"""

import html
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)
e = html.escape


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, str]
    form: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def arg(self, name: str, default: str = "") -> str:
        return self.query.get(name, default).strip()


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


def html_response(body: str, status: int = 200) -> Response:
    return Response(status, body.encode("utf-8"))


def text_response(
    body: str, status: int = 200, content_type: str = "text/plain"
) -> Response:
    return Response(status, body.encode("utf-8"), f"{content_type}; charset=utf-8")


def redirect(location: str) -> Response:
    return Response(303, b"", headers=(("Location", location),))


def file_response(data: bytes, content_type: str, name: str = "") -> Response:
    headers = (("Content-Disposition", f'inline; filename="{name}"'),) if name else ()
    return Response(200, data, content_type, headers)


Handler = Callable[..., Response]
PARAM_RE = re.compile(r"<(int|str):(\w+)>")


def _compile(pattern: str) -> re.Pattern[str]:
    def group(match: re.Match[str]) -> str:
        kind, name = match.groups()
        return rf"(?P<{name}>\d+)" if kind == "int" else rf"(?P<{name}>[^/]+)"

    return re.compile("^" + PARAM_RE.sub(group, pattern) + "$")


class App:
    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler, bool]] = []

    def route(
        self, method: str, pattern: str, same_origin: bool = True
    ) -> Callable[[Handler], Handler]:
        """`same_origin=False` is for API routes that check a token instead."""

        def register(handler: Handler) -> Handler:
            self._routes.append((method, _compile(pattern), handler, same_origin))
            return handler

        return register

    def handle(self, request: Request) -> Response:
        allowed = False
        for method, pattern, handler, check_origin in self._routes:
            match = pattern.match(request.path)
            if not match:
                continue
            if method != request.method:
                allowed = True
                continue
            if request.method == "POST" and check_origin and not _same_origin(request):
                return text_response("forbidden", 403)
            params = {
                k: int(v) if v.isdigit() else v for k, v in match.groupdict().items()
            }
            try:
                return handler(request, **params)
            except Exception:
                log.exception("web: %s %s failed", request.method, request.path)
                return text_response("error", 500)
        return text_response(
            "method not allowed" if allowed else "not found", 405 if allowed else 404
        )


def _same_origin(request: Request) -> bool:
    """POST forms must come from this site (Origin, else Referer)."""
    source = request.headers.get("origin") or request.headers.get("referer") or ""
    host = request.headers.get("host") or ""
    return bool(host) and urlparse(source).netloc == host


def parse_request(
    method: str, raw_path: str, headers: dict[str, str], body: bytes
) -> Request:
    url = urlparse(raw_path)
    query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
    form: dict[str, str] = {}
    if body:
        form = {
            k: v[-1]
            for k, v in parse_qs(
                body.decode("utf-8", "replace"), keep_blank_values=True
            ).items()
        }
    return Request(
        method,
        url.path or "/",
        query,
        form,
        {k.lower(): v for k, v in headers.items()},
        body,
    )
