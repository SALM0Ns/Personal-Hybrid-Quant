"""Loopback-only chart and on-demand informational BTC analysis."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from quant.app.analysis import (
    MarketDataError,
    build_analysis,
    failure_payload,
    fetch_recent_market,
    market_payload,
    utc_now,
)
from quant.app.preview import PreviewDataError, PreviewNotFoundError, load_preview
from quant.ingestion.pipeline import latest_closed

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
    """Historical files remain read-only; recent analysis is in memory only."""
    refresh_lock = Lock()

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
                status,
                json.dumps(payload, allow_nan=False, ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            route = urlsplit(self.path).path
            if route not in {"/api/market", "/api/analyze"}:
                self._json(HTTPStatus.NOT_FOUND, failure_payload("Not found"))
                return
            origin = self.headers.get("Origin")
            allowed = {
                f"http://127.0.0.1:{self.server.server_port}",
                f"http://localhost:{self.server.server_port}",
            }
            if origin is not None and origin not in allowed:
                self._json(
                    HTTPStatus.FORBIDDEN, failure_payload("Local origin required")
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 or (
                    self.headers.get_content_type() != "application/json"
                ):
                    raise ValueError("Expected a small JSON request")
                if json.loads(self.rfile.read(length)) != {}:
                    raise ValueError("Only an empty analysis request is supported")
            except (ValueError, UnicodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, failure_payload(str(exc)))
                return
            if not refresh_lock.acquire(blocking=False):
                self._json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    failure_payload("A market refresh is already running; wait for it"),
                )
                return
            try:
                window = fetch_recent_market()
                payload = (
                    build_analysis(window)
                    if route == "/api/analyze"
                    else market_payload(window)
                )
                now = utc_now()
                if latest_closed(now) != window.latest or now < window.observed_at:
                    raise MarketDataError(
                        "Market window is no longer current; refresh again"
                    )
            except MarketDataError as exc:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, failure_payload(str(exc)))
            except Exception:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    failure_payload(
                        "Analysis failed; no current assessment is available"
                    ),
                )
            else:
                self._json(HTTPStatus.OK, payload)
            finally:
                refresh_lock.release()

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
    """Serve only on loopback; Ctrl-C stops the application."""
    if not (WEB_ROOT / STATIC_FILES["/vendor/lightweight-charts.js"][0]).is_file():
        raise FileNotFoundError(
            "TradingView dependency missing; run npm ci --prefix web"
        )
    with ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(data_root, limit=limit)
    ) as server:
        print(f"PQTA informational BTC analysis: http://127.0.0.1:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
