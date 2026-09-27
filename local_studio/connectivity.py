"""Bounded, read-only discovery and tiny model tests with safe public results."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config_store import ConfigError, normalize_base_url


_TIMEOUT = httpx.Timeout(40.0, connect=12.0, pool=5.0, write=10.0)
_MAX_RESPONSE = 2 * 1024 * 1024
_ZEP_LIST = "https://api.getzep.com/api/v2/graph/list-all"


def _profile(profile: Any, *, model: bool = True, require_model: bool = False) -> dict:
    if not isinstance(profile, dict):
        raise ConfigError("请先保存并选择配置。")
    key = profile.get("key", "")
    if not isinstance(key, str) or len(key) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise ConfigError("API Key 格式不正确。")
    result = {"key": key.strip()}
    if model:
        result["base_url"] = normalize_base_url(profile.get("base_url", ""))
        name = profile.get("model", "")
        if (not isinstance(name, str) or len(name) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ConfigError("模型名称格式不正确。")
        if require_model and not name.strip():
            raise ConfigError("请先获取并选择模型，或手动填写模型名称。")
        result["model"] = name.strip()
    elif not result["key"]:
        raise ConfigError("请先填写 Zep API Key。")
    return result


def _request_json(method: str, url: str, *, key: str, payload: dict | None = None,
                  zep: bool = False) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "User-Agent": "MiroFish-Studio/1"}
    if key:
        headers["Authorization"] = ("Api-Key " if zep else "Bearer ") + key
    options: dict[str, Any] = {"headers": headers}
    if payload is not None:
        options["json"] = payload
    if zep:
        options["params"] = {"pageNumber": 1, "pageSize": 1}
    started = time.monotonic()
    # Retain the user's proxy/VPN settings, but never forward credentials on a redirect.
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
        with client.stream(method, url, **options) as response:
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > _MAX_RESPONSE or time.monotonic() - started > 60:
                    raise ValueError("response_limit")
            try:
                return response.status_code, json.loads(chunks)
            except (ValueError, UnicodeError):
                return response.status_code, None


def _failure(status: int | None, *, discovery: bool = False) -> str:
    if status is not None and 300 <= status < 400:
        return "接口返回了重定向。为保护密钥，请填写最终的 API Base URL 后重试。"
    messages = {
        400: "服务商未接受请求，请核对接口地址、模型名称及该模型的调用要求。",
        401: "认证失败，请检查 API Key 是否正确或已过期。",
        403: "该密钥没有访问权限，请检查服务商账户和项目授权。",
        404: "未找到接口或模型，请核对 Base URL 与模型名称。",
        408: "服务商响应超时，请稍后重试。",
        429: "服务商限流或额度不足，请稍后重试或换用其他配置。",
    }
    if discovery and status in {404, 405, 501}:
        return "该服务未提供兼容的模型列表接口，请手动填写模型名称；仍可保存并测试调用。"
    if status in messages:
        return messages[status]
    if status is not None and status >= 500:
        return "服务商暂时不可用，请稍后重试。"
    return "接口响应不符合预期，请检查 Base URL 和服务商兼容性。"


def _exception_message(error: Exception) -> str:
    if isinstance(error, ConfigError):
        return str(error)
    if isinstance(error, httpx.TimeoutException):
        return "连接超时，请检查网络、代理或服务地址后重试。"
    if isinstance(error, httpx.TransportError):
        return "无法连接服务，请检查网络、代理、证书和 Base URL。"
    return "无法验证接口响应，请检查服务商兼容性；模型名称也可以手动填写。"


def _result(started: float, *, ok: bool, status: int | None, message: str, **extra) -> dict:
    return {"ok": ok, "status": status, "message": message,
            "latency_ms": round((time.monotonic() - started) * 1000), **extra}


def discover_models(profile: dict) -> dict:
    started = time.monotonic()
    status = None
    try:
        selected = _profile(profile)
        status, payload = _request_json("GET", selected["base_url"] + "/models", key=selected["key"])
        if not 200 <= status < 300:
            return _result(started, ok=False, status=status, message=_failure(status, discovery=True), models=[])
        entries = payload.get("data", payload.get("models")) if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("model_list_schema")
        models: list[str] = []
        for entry in entries:
            name = entry if isinstance(entry, str) else entry.get("id", entry.get("name")) if isinstance(entry, dict) else None
            if (isinstance(name, str) and name.strip() and len(name) <= 256
                    and not any(ord(c) < 32 or ord(c) == 127 for c in name)
                    and (not selected["key"] or selected["key"] not in name)):
                normalized = name.strip()
                if normalized not in models:
                    models.append(normalized)
        message = f"已获取 {len(models)} 个模型，请选择适合推演的对话模型。" if models else "接口未返回可选模型，请手动填写模型名称后测试调用。"
        return _result(started, ok=bool(models), status=status, message=message, models=models)
    except Exception as error:
        return _result(started, ok=False, status=status, message=_exception_message(error), models=[])


def test_model(profile: dict) -> dict:
    started = time.monotonic()
    status = None
    try:
        selected = _profile(profile, require_model=True)
        request = {"model": selected["model"], "messages": [{"role": "user", "content": "Reply OK."}],
                   "max_tokens": 16, "stream": False}
        url = selected["base_url"] + "/chat/completions"
        status, payload = _request_json("POST", url, key=selected["key"], payload=request)
        # Newer reasoning APIs reject max_tokens; one bounded compatibility retry.
        error = payload.get("error") if isinstance(payload, dict) else None
        if status == 400 and isinstance(error, dict) and error.get("param") == "max_tokens":
            request.pop("max_tokens")
            request["max_completion_tokens"] = 16
            status, payload = _request_json("POST", url, key=selected["key"], payload=request)
        if not 200 <= status < 300:
            return _result(started, ok=False, status=status, message=_failure(status))
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if (not isinstance(choices, list) or not choices or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get("message"), dict)):
            raise ValueError("completion_schema")
        return _result(started, ok=True, status=status, message="连接成功，模型已返回有效响应。")
    except Exception as error:
        return _result(started, ok=False, status=status, message=_exception_message(error))


def test_zep(profile: dict) -> dict:
    """Match installed zep-cloud 3.25.0 graph.list_all; never create a graph."""
    started = time.monotonic()
    status = None
    try:
        selected = _profile(profile, model=False)
        status, payload = _request_json("GET", _ZEP_LIST, key=selected["key"], zep=True)
        if not 200 <= status < 300:
            return _result(started, ok=False, status=status, message=_failure(status))
        if not isinstance(payload, dict):
            raise ValueError("graph_list_schema")
        graphs = payload.get("graphs")
        # The SDK makes graphs optional; an explicitly empty count is also valid.
        empty_account = graphs is None and any(
            type(payload.get(field)) is int and payload[field] == 0 for field in ("row_count", "total_count")
        )
        if not empty_account and (not isinstance(graphs, list) or any(not isinstance(graph, dict) for graph in graphs)):
            raise ValueError("graph_list_schema")
        for field in ("row_count", "total_count"):
            if field in payload and payload[field] is not None and type(payload[field]) is not int:
                raise ValueError("graph_list_count_schema")
        return _result(started, ok=True, status=status, message="Zep 连接成功，密钥可读取当前项目。")
    except Exception as error:
        return _result(started, ok=False, status=status, message=_exception_message(error))
