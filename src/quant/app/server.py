"""Loopback-only HTTP interface for the historical candlestick preview."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from quant.app.preview import PreviewDataError, PreviewNotFoundError, load_preview

WEB_ROOT = Path(__file__).resolve().parents[3] / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/vendor/lightweight-charts.js": (
        "node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js",
        "text/javascript; charset=utf-8",
    ),
}


def make_handler(data_root: Path, *, limit: int = 500) -> type[BaseHTTPRequestHandler]:
    """Bind one read-only data root to the local preview routes."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; img-src 'self' data:",
            )
            self.end_headers()
            self.wfile.write(content)

        def _json(self, status: HTTPStatus, payload: dict) -> None:
            self._send(
                status, json.dumps(payload).encode(), "application/json; charset=utf-8"
            )

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            route = urlsplit(self.path).path
            if route == "/api/preview":
                try:
                    payload = load_preview(data_root, limit=limit)
                except PreviewNotFoundError as exc:
                    self._json(
                        HTTPStatus.NOT_FOUND, {"error": str(exc), "signal": "NO SIGNAL"}
                    )
                except PreviewDataError as exc:
                    self._json(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        {"error": str(exc), "signal": "NO SIGNAL"},
                    )
                else:
                    self._json(HTTPStatus.OK, payload)
                return
            if route not in STATIC_FILES:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            filename, content_type = STATIC_FILES[route]
            try:
                content = (WEB_ROOT / filename).read_bytes()
            except FileNotFoundError:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "Frontend dependency missing; run npm ci --prefix web"},
                )
                return
            self._send(HTTPStatus.OK, content, content_type)

    return Handler


def serve(data_root: Path, *, port: int = 8765, limit: int = 500) -> None:
    """Serve only on loopback; Ctrl-C stops the preview."""
    if not (WEB_ROOT / STATIC_FILES["/vendor/lightweight-charts.js"][0]).is_file():
        raise FileNotFoundError(
            "TradingView dependency missing; run npm ci --prefix web"
        )
    with ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(data_root, limit=limit)
    ) as server:
        print(f"Historical preview: http://127.0.0.1:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
