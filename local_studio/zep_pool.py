"""Zep failover with durable graph ownership and no replay of uncertain writes.

Only a rejected *new* graph creation may move to a different credential group.
Existing graphs, batches, episodes, nodes and edges remain in their original
account. Empty groups are isolated by key ID. SDK retries are disabled here so
a lost POST response cannot silently create duplicate episodes.
"""

from __future__ import annotations

import inspect
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable


class ZepPoolError(RuntimeError):
    """A safe, actionable error without API keys, payloads or provider bodies."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_POOLS: dict[tuple, "ZepPool"] = {}
_POOLS_GUARD = threading.Lock()


def _local_lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path.resolve()), threading.RLock())


@contextmanager
def _state_lock(directory: Path):
    """Serialize atomic read/merge/write across threads and engine processes."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".zep_pool.lock"
    with _local_lock(path), path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (OSError, ValueError):
        # A corrupt ownership journal must never be treated as an empty one.
        raise ZepPoolError("Zep 图谱归属记录无法读取，请先恢复本地备份。") from None


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _group(candidate: dict) -> str:
    group = str(candidate.get("group") or "").strip()
    return "group:" + group if group else "key:" + candidate["id"]


def _status(error: BaseException) -> int | None:
    value = getattr(error, "status_code", None)
    return value if isinstance(value, int) else None


def _transient(error: BaseException) -> bool:
    status = _status(error)
    if status in {408, 429} or (status is not None and 500 <= status <= 599):
        return True
    try:
        import httpx

        if isinstance(error, httpx.TransportError):
            return True
    except ImportError:
        pass
    return isinstance(error, (ConnectionError, TimeoutError, OSError))


def _retry_after(error: BaseException, now: float) -> float:
    headers = getattr(error, "headers", None) or {}
    value = next((v for k, v in headers.items() if str(k).lower() == "retry-after"), None)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = parsed.timestamp() - now
        except (TypeError, ValueError, OverflowError):
            seconds = 60
    return max(1.0, min(seconds, 3600.0))


def _safe_error(error: BaseException) -> BaseException:
    """Preserve SDK status/type for caller reconciliation; discard unsafe text."""
    code = _status(error)
    messages = {
        401: "Zep 密钥已失效，且没有同组可用的备用密钥。",
        403: "Zep 密钥无权访问当前图谱，且没有同组可用的备用密钥。",
        404: "当前 Zep 账号中找不到该图谱或记录；为保护数据未切换到其他账号。",
        429: "Zep 当前可用密钥均受到限流，请等待冷却后重试。",
    }
    message = messages.get(code, "Zep 请求暂时失败，请稍后重试。")
    if code is not None:
        try:
            from zep_cloud.core.api_error import ApiError

            if isinstance(error, ApiError):
                headers = {"Retry-After": str(int(_retry_after(error, time.time())))} if code == 429 else None
                if type(error) is ApiError:
                    return ApiError(status_code=code, body={"message": message}, headers=headers)
                try:
                    return type(error)(body={"message": message}, headers=headers)
                except TypeError:
                    return ApiError(status_code=code, body={"message": message}, headers=headers)
            return ApiError(status_code=code, body={"message": message})
        except ImportError:
            pass
        return ZepPoolError(message, code)
    if _transient(error):
        try:
            import httpx

            return httpx.TransportError("Zep 网络请求中断；写入不会自动重发，请先核对已保存进度。")
        except ImportError:
            return ConnectionError("Zep 网络连接暂时不可用。")
    return ZepPoolError("Zep 请求未完成；请检查配置与输入，密钥和服务端详情已隐藏。")


class ZepPool:
    """Shared credentials/health, with per-resource affinity and scoped clients."""

    def __init__(self, root: str | Path, store: Any, client_factory: Callable[[str], Any], *, clock=time.time):
        self.root = Path(root).resolve()
        self.directory = self.root / "studio_data"
        self.store = store
        self.client_factory = client_factory
        self.clock = clock
        self._clients: dict[str, tuple[str, Any]] = {}
        self._clients_lock = threading.RLock()

    def client(self) -> "RotatingZepClient":
        # Do not cache this facade: batch reconciliation context belongs to its
        # service instance and thread, never to other users or graphs.
        return RotatingZepClient(self)

    def _snapshot(self) -> dict:
        with _state_lock(self.directory):
            data = _read_json(self.directory / "zep_bindings.json", {"version": 1, "graphs": {}, "resources": {}})
        if data.get("version") != 1 or not isinstance(data.get("graphs"), dict) or not isinstance(data.get("resources"), dict):
            raise ZepPoolError("Zep 图谱归属记录格式无效，请先恢复本地备份。")
        return data

    def _remember(self, entries: list[tuple[str, str, dict]], *, reassign_graph: str | None = None) -> None:
        if not entries:
            return
        with _state_lock(self.directory):
            path = self.directory / "zep_bindings.json"
            state = _read_json(path, {"version": 1, "graphs": {}, "resources": {}})
            changed = False
            for table, identity, binding in entries:
                current = state[table].get(identity)
                if current and current["group"] != binding["group"]:
                    if table != "graphs" or identity != reassign_graph:
                        raise ZepPoolError("Zep 记录已属于另一账号组，已阻止跨账号访问。")
                if current != binding:
                    state[table][identity] = dict(binding)
                    changed = True
            if changed:
                _atomic_json(path, state)

    def _health(self, key_id: str, error: BaseException | None = None, *, reset: bool = False) -> None:
        now = self.clock()
        with _state_lock(self.directory):
            path = self.directory / "zep_health.json"
            data = _read_json(path, {"updated_at": now, "keys": {}})
            old = data.setdefault("keys", {}).get(key_id, {}) if not reset else {}
            code = _status(error) if error else None
            if error:
                if code in {401, 403}:
                    status, cooldown = "unavailable", 300.0
                elif code == 429:
                    status, cooldown = "rate_limited", _retry_after(error, now)
                elif _transient(error):
                    status, cooldown = "connection_error", 10.0
                else:
                    # A missing graph or invalid input says nothing about the
                    # key's global health and must not disable other graphs.
                    return
            else:
                status, cooldown = "unchecked" if reset else "available", 0.0
            data["keys"][key_id] = {
                "id": key_id, "status": status, "last_status": code,
                "cooldown_until": now + cooldown if cooldown else 0,
                "failures": int(old.get("failures", 0)) + 1 if error else 0,
                "last_success_at": old.get("last_success_at") if error or reset else now,
                "fingerprint": old.get("fingerprint"),
            }
            data["updated_at"] = now
            _atomic_json(path, data)

    def _raw(self, candidate: dict) -> Any:
        with self._clients_lock:
            current = self._clients.get(candidate["id"])
            if current is None or current[0] != candidate["key"]:
                # Updating a key releases its old cooldown, including after an
                # engine restart. Only a one-way fingerprint is persisted.
                fingerprint = hashlib.sha256(candidate["key"].encode("utf-8")).hexdigest()
                with _state_lock(self.directory):
                    path = self.directory / "zep_health.json"
                    data = _read_json(path, {"updated_at": self.clock(), "keys": {}})
                    row = data.setdefault("keys", {}).get(candidate["id"], {})
                    if row.get("fingerprint") != fingerprint:
                        data["keys"][candidate["id"]] = {
                            "id": candidate["id"], "status": "unchecked", "last_status": None,
                            "cooldown_until": 0, "failures": 0, "last_success_at": None,
                            "fingerprint": fingerprint,
                        }
                        data["updated_at"] = self.clock()
                        _atomic_json(path, data)
                raw = self.client_factory(candidate["key"])
                self._clients[candidate["id"]] = (candidate["key"], raw)
            return self._clients[candidate["id"]][1]

    @staticmethod
    def _method(raw: Any, path: tuple[str, ...]) -> Any:
        for part in path:
            raw = getattr(raw, part)
        return raw

    def _call(self, candidate: dict, path: tuple[str, ...], args: tuple, kwargs: dict) -> Any:
        method = self._method(self._raw(candidate), path)
        forwarded = dict(kwargs)
        # Fern retries even POST 5xx/409 by default. Bound retries must be ours.
        options = dict(forwarded.get("request_options") or {})
        options["max_retries"] = 0
        forwarded["request_options"] = options
        return method(*args, **forwarded)

    def _scope(self, facade: "RotatingZepClient", path: tuple[str, ...], args: tuple, kwargs: dict, candidate: dict) -> tuple[list[str], list[str]]:
        values = dict(kwargs)
        method = self._method(self._raw(candidate), path)
        try:
            values.update(inspect.signature(method).bind_partial(*args, **kwargs).arguments)
        except (TypeError, ValueError):
            pass
        clean = tuple(p for p in path if p != "with_raw_response")
        name = clean[-1]
        # Permit fake clients and C-implemented callables without signatures.
        if args:
            if clean[0] == "batch" and name in {"get", "delete", "add", "process", "list_items"}:
                values.setdefault("batch_id", args[0])
            elif name == "get_by_graph_id" or clean == ("graph", "get") or clean == ("graph", "delete"):
                values.setdefault("graph_id", args[0])
            elif len(clean) == 3 and name in {"get", "delete", "get_nodes_and_edges"}:
                values.setdefault("uuid_", args[0])
            elif name in {"get_edges", "get_episodes"}:
                values.setdefault("node_uuid", args[0])
        graphs = []
        if _identifier(values.get("graph_id")):
            graphs.append(values["graph_id"])
        if isinstance(values.get("graph_ids"), (list, tuple)):
            graphs.extend(v for v in values["graph_ids"] if _identifier(v))
        metadata = values.get("metadata")
        if clean[0] == "batch" and isinstance(metadata, dict) and _identifier(metadata.get("graph_id")):
            graphs.append(metadata["graph_id"])
        for item in values.get("items", []) or []:
            if _identifier(_field(item, "graph_id")):
                graphs.append(_field(item, "graph_id"))
        resources = []
        if _identifier(values.get("batch_id")):
            resources.append("batch:" + values["batch_id"])
        if len(clean) >= 3 and clean[1] in {"node", "edge", "episode"}:
            resource_id = values.get("uuid_") or values.get("node_uuid") or values.get("edge_uuid") or values.get("episode_uuid")
            if _identifier(resource_id):
                resources.append(clean[1] + ":" + resource_id)
        if not graphs and not resources and clean == ("batch", "list"):
            graph_id = getattr(facade._context, "batch_graph", None)
            if graph_id:
                graphs.append(graph_id)
        return list(dict.fromkeys(graphs)), list(dict.fromkeys(resources))

    def _record_result(self, result: Any, path: tuple[str, ...], binding: dict, graphs: list[str], resources: list[str]) -> None:
        entries = [("graphs", g, {**binding, "graph_id": g}) for g in graphs]
        entries += [("resources", r, dict(binding)) for r in resources]
        clean = tuple(p for p in path if p != "with_raw_response")
        if "with_raw_response" in path:
            result = _field(result, "data")
        # Only known structural fields are traversed, never content/metadata.
        def visit(value: Any, kind: str | None = None, depth: int = 0):
            if value is None or depth > 5 or isinstance(value, (str, bytes, int, float, bool)):
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    visit(item, kind, depth + 1)
                return
            local = dict(binding)
            graph_id = _identifier(_field(value, "graph_id"))
            if graph_id:
                local["graph_id"] = graph_id
                entries.append(("graphs", graph_id, dict(local)))
            metadata = _field(value, "metadata")
            if isinstance(metadata, dict) and _identifier(metadata.get("graph_id")) and _identifier(_field(value, "batch_id")):
                local["graph_id"] = metadata["graph_id"]
            for field_name, resource_kind in (("batch_id", "batch"), ("episode_uuid", "episode"), ("source_node_uuid", "node"), ("target_node_uuid", "node")):
                identity = _identifier(_field(value, field_name))
                if identity:
                    entries.append(("resources", resource_kind + ":" + identity, dict(local)))
            identity = _identifier(_field(value, "uuid_")) or _identifier(_field(value, "uuid"))
            if identity and kind in {"node", "edge", "episode"}:
                entries.append(("resources", kind + ":" + identity, dict(local)))
            for field_name, nested_kind in (("nodes", "node"), ("edges", "edge"), ("episodes", "episode"), ("batches", "batch"), ("items", "batch_item")):
                nested = _field(value, field_name)
                if isinstance(nested, (list, tuple)):
                    for item in nested:
                        if _identifier(item) and nested_kind in {"node", "edge", "episode"}:
                            entries.append(("resources", nested_kind + ":" + item, dict(local)))
                        else:
                            visit(item, nested_kind, depth + 1)
        kind = clean[1] if len(clean) >= 3 else None
        if clean in {("graph", "add"), ("graph", "add_batch")}:
            kind = "episode"
        elif clean[-1] == "get_edges":
            kind = "edge"
        elif clean[-1] == "get_episodes":
            kind = "episode"
        visit(result, kind)
        self._remember(entries)

    def invoke(self, facade: "RotatingZepClient", path: tuple[str, ...], args: tuple, kwargs: dict) -> Any:
        candidates = [dict(c) for c in self.store.zep_candidates() if c.get("enabled", True) and c.get("key")]
        if not candidates:
            raise ZepPoolError("没有已启用的 Zep 密钥，请在控制台添加或启用密钥。")
        auto = bool(self.store.public().get("auto_zep", True))
        for candidate in candidates:
            self._raw(candidate)
        graphs, resources = self._scope(facade, path, args, kwargs, candidates[0])
        clean = tuple(p for p in path if p != "with_raw_response")
        is_new_create = clean == ("graph", "create")
        is_read = clean[-1].startswith(("get", "list", "search"))
        lock_id = graphs[0] if graphs else resources[0] if resources else "unscoped"
        with _local_lock(self.directory / ("call-" + hashlib.sha256(lock_id.encode("utf-8")).hexdigest())):
            snapshot = self._snapshot()
            bindings = [snapshot["graphs"][g] for g in graphs if g in snapshot["graphs"]]
            bindings += [snapshot["resources"][r] for r in resources if r in snapshot["resources"]]
            for binding in list(bindings):
                graph_id = binding.get("graph_id")
                if graph_id and graph_id in snapshot["graphs"]:
                    bindings.insert(0, snapshot["graphs"][graph_id])
                    if graph_id not in graphs:
                        graphs.append(graph_id)
            groups = {b["group"] for b in bindings}
            if len(groups) > 1:
                raise ZepPoolError("此请求包含不同 Zep 账号组的记录，已阻止混用。")
            # Unknown existing IDs are initially restricted to the selected
            # account too; absence of a binding is not permission to roam.
            original = bindings[0] if bindings else None
            group = original["group"] if original else _group(candidates[0])
            may_choose_account = is_new_create and not original
            preferred = original["key_id"] if original else candidates[0]["id"]
            ordered = sorted(candidates, key=lambda c: c["id"] != preferred)
            if not may_choose_account:
                ordered = [c for c in ordered if _group(c) == group]
            if not auto:
                ordered = [c for c in ordered if c["id"] == preferred]
            if not ordered:
                raise ZepPoolError("当前图谱绑定的 Zep 账号没有可用密钥，请恢复原密钥或添加同组备用密钥。")
            health = get_health(self.root)
            cooling = {
                e["id"]: e for e in health["entries"]
                if e.get("cooldown_until", 0) > self.clock()
                # A failed write may have succeeded remotely. Safe GETs must
                # remain available for immediate engine reconciliation.
                and not (is_read and e.get("status") == "connection_error")
            }
            ordered = [c for c in ordered if c["id"] not in cooling]
            if not ordered:
                raise _safe_error(ZepPoolError("当前图谱所属账号的密钥都在冷却中。", 429)) from None
            last_error: BaseException | None = None
            for candidate in ordered:
                binding = {"group": _group(candidate), "key_id": candidate["id"], "graph_id": graphs[0] if len(graphs) == 1 else None}
                if clean[0] == "batch" and graphs:
                    facade._context.batch_graph = graphs[0]
                verifying = False
                try:
                    # Verify a declared sibling key can see the actual graph
                    # before any write or descendant read is forwarded.
                    if not may_choose_account and (candidate["id"] != preferred or (not original and not is_read)):
                        verifying = True
                        for graph_id in graphs:
                            self._call(candidate, ("graph", "get"), (graph_id,), {})
                        verifying = False
                    if may_choose_account:
                        self._remember(
                            [("graphs", g, {**binding, "graph_id": g}) for g in graphs],
                            reassign_graph=graphs[0] if len(graphs) == 1 else None,
                        )
                    result = self._call(candidate, path, args, kwargs)
                except Exception as error:
                    if isinstance(error, ZepPoolError):
                        raise
                    self._health(candidate["id"], error)
                    last_error = error
                    # Definite rejection is safe to try another key. A timeout
                    # or 5xx on a write is ambiguous: keep the ownership journal
                    # and surface it for the engine's existing reconciliation.
                    can_rotate = _status(error) in {401, 403, 429} or (is_read and _transient(error)) or (verifying and _status(error) == 404)
                    if not auto or not can_rotate:
                        raise _safe_error(error) from None
                    continue
                self._health(candidate["id"])
                self._record_result(result, path, binding, graphs, resources)
                return result
            if last_error is not None:
                raise _safe_error(last_error) from None
            raise ZepPoolError("Zep 暂无可用密钥。")


class _ResourceProxy:
    def __init__(self, client: "RotatingZepClient", path: tuple[str, ...]):
        self._client = client
        self._path = path

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        path = self._path + (name,)
        if name in {"node", "edge", "episode", "observation", "thread_summary", "with_raw_response"}:
            return _ResourceProxy(self._client, path)

        def call(*args, **kwargs):
            return self._client._pool.invoke(self._client, path, args, kwargs)

        return call


class RotatingZepClient:
    def __init__(self, pool: ZepPool):
        self._pool = pool
        self._context = threading.local()
        self.graph = _ResourceProxy(self, ("graph",))
        self.batch = _ResourceProxy(self, ("batch",))

    def __repr__(self) -> str:
        return "<RotatingZepClient credentials=redacted>"


def get_health(root: str | Path) -> dict:
    """Safe read-only status for the local controller; never includes keys."""
    directory = Path(root).resolve() / "studio_data"
    if not directory.exists():
        return {"updated_at": None, "entries": [], "bindings": {"graphs": 0, "resources": 0}}
    with _state_lock(directory):
        data = _read_json(directory / "zep_health.json", {"updated_at": None, "keys": {}})
        bindings = _read_json(directory / "zep_bindings.json", {"graphs": {}, "resources": {}})
    # Whitelist even persisted fields; an accidentally edited status file must
    # never become a credential-bearing API response.
    allowed = {"id", "status", "last_status", "cooldown_until", "failures", "last_success_at"}
    return {
        "updated_at": data.get("updated_at"),
        "entries": [{k: v for k, v in e.items() if k in allowed} for e in data.get("keys", {}).values()],
        "bindings": {"graphs": len(bindings.get("graphs", {})), "resources": len(bindings.get("resources", {}))},
    }


def get_studio_zep_client(root: str | Path, timeout: float, client_factory: Callable[[str, float], Any]) -> RotatingZepClient | None:
    from .config_store import ConfigStore

    root = Path(root).resolve()
    store = ConfigStore(root)
    if not store.zep_candidates():
        if (root / "studio_data" / "config.json").exists():
            raise ZepPoolError("没有已启用的 Zep 密钥，请在控制台添加或启用密钥。")
        return None
    identity = (str(root), timeout, client_factory)
    with _POOLS_GUARD:
        if identity not in _POOLS:
            _POOLS[identity] = ZepPool(root, store, lambda key: client_factory(key, timeout))
        return _POOLS[identity].client()


def clear_pool_cache() -> None:
    with _POOLS_GUARD:
        _POOLS.clear()
