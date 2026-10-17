"""A deterministic OpenAI-compatible HTTP server for pipeline tests.

The product talks to any ``/v1/chat/completions`` endpoint through the real
OpenAI SDK, so the cheapest faithful test double is a real HTTP server on
loopback. Tests register routes (substring matchers over the whole prompt) and
an unmatched request fails loudly with the prompt text, which keeps the
prompt/response contract visible instead of silently returning something.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable


@dataclass
class ProviderError:
    """Return from a route to make the provider reject the request."""

    status: int
    message: str = "provider error"


@dataclass
class Route:
    name: str
    contains: tuple[str, ...]
    respond: Any
    predicate: Callable[[dict], bool] | None = None
    hits: int = 0

    def matches(self, text: str, payload: dict) -> bool:
        if any(fragment not in text for fragment in self.contains):
            return False
        return self.predicate(payload) if self.predicate else True


@dataclass
class RecordedRequest:
    path: str
    payload: dict
    route: str | None
    text: str = ""


@dataclass
class FakeLLM:
    routes: list[Route] = field(default_factory=list)
    requests: list[RecordedRequest] = field(default_factory=list)
    unmatched: list[RecordedRequest] = field(default_factory=list)
    models: tuple[str, ...] = ("fake-model",)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---- configuration -------------------------------------------------
    def route(self, name: str, *, contains: str | Iterable[str] = (), respond: Any,
              predicate: Callable[[dict], bool] | None = None) -> Route:
        """Register a response. ``respond`` may be text, JSON-able data, or a callable
        receiving the request payload. Earlier routes win."""
        fragments = (contains,) if isinstance(contains, str) else tuple(contains)
        route = Route(name, fragments, respond, predicate)
        self.routes.append(route)
        return route

    # ---- introspection -------------------------------------------------
    @property
    def base_url(self) -> str:
        assert self._server is not None, "FakeLLM.start() was not called"
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def hits(self, name: str) -> int:
        return sum(1 for r in self.requests if r.route == name)

    # ---- lifecycle -----------------------------------------------------
    def start(self) -> "FakeLLM":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # keep pytest output clean
                return

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.rstrip("/").endswith("/models"):
                    self._send(200, {"object": "list", "data": [
                        {"id": name, "object": "model"} for name in owner.models]})
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send(400, {"error": {"message": "invalid JSON"}})
                if not self.path.rstrip("/").endswith("/chat/completions"):
                    return self._send(404, {"error": {"message": "not found"}})
                status, body = owner._complete(self.path, payload)
                self._send(status, body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # ---- request handling ----------------------------------------------
    @staticmethod
    def prompt_text(payload: dict) -> str:
        parts = []
        for message in payload.get("messages") or []:
            content = message.get("content")
            if isinstance(content, list):
                content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
            parts.append(str(content or ""))
        return "\n".join(parts)

    def _complete(self, path: str, payload: dict) -> tuple[int, dict]:
        text = self.prompt_text(payload)
        with self._lock:
            selected = next((r for r in self.routes if r.matches(text, payload)), None)
            record = RecordedRequest(path, payload, selected.name if selected else None, text)
            self.requests.append(record)
            if selected is None:
                self.unmatched.append(record)
                # 400 is not retried by the OpenAI SDK, so a missing route fails fast.
                return 400, {"error": {"message": "FakeLLM: no route for prompt: " + text[:600],
                                       "type": "fake_llm_unmatched"}}
            selected.hits += 1
        content = selected.respond(payload) if callable(selected.respond) else selected.respond
        if isinstance(content, ProviderError):
            return content.status, {"error": {"message": content.message, "type": "provider_error"}}
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return 200, {
            "id": f"chatcmpl-fake-{len(self.requests)}", "object": "chat.completion", "created": 0,
            "model": payload.get("model", "fake-model"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
