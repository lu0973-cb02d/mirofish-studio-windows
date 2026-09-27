"""Atomic, Windows-user-bound credential storage for the local Studio.

Only ``runtime_*`` and ``zep_candidates`` return secrets; they are backend-only
interfaces. ``public`` and every mutation return an explicit public whitelist.
"""

from __future__ import annotations

import base64
import copy
import ctypes
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit


class ConfigError(ValueError):
    """A safe, user-readable configuration error without credential contents."""


class _SecretStorageError(ConfigError):
    """Distinguish a vault failure from a skippable malformed legacy profile."""


class SecretCodec(Protocol):
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


class DPAPICodec:
    """Current-user Windows DPAPI, without any plaintext fallback."""

    _PREFIX = "dpapi:v1:"

    def __init__(self) -> None:
        if os.name != "nt":
            raise ConfigError("密钥保险箱需要 Windows DPAPI；当前环境不支持安全保存。")

    @staticmethod
    def _transform(raw: bytes, *, decrypt: bool) -> bytes:
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        source_buffer = ctypes.create_string_buffer(raw)
        source = DATA_BLOB(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        destination = DATA_BLOB()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(DATA_BLOB)]
        function.restype = wintypes.BOOL
        try:
            # CRYPTPROTECT_UI_FORBIDDEN; omitting LOCAL_MACHINE binds to this user.
            if not function(ctypes.byref(source), None, None, None, None, 1,
                            ctypes.byref(destination)):
                raise ConfigError("Windows 无法保护或解锁密钥，请使用原来的 Windows 用户账户。")
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            ctypes.memset(source_buffer, 0, len(raw))
            if destination.pbData:
                ctypes.memset(destination.pbData, 0, destination.cbData)
                kernel32.LocalFree(destination.pbData)

    def encrypt(self, plaintext: str) -> str:
        try:
            return self._PREFIX + base64.b64encode(
                self._transform(plaintext.encode("utf-8"), decrypt=False)
            ).decode("ascii")
        except ConfigError:
            raise
        except Exception:
            raise ConfigError("Windows 密钥加密失败，未保存配置。") from None

    def decrypt(self, ciphertext: str) -> str:
        if not isinstance(ciphertext, str) or not ciphertext.startswith(self._PREFIX):
            raise ConfigError("密钥保险箱格式无效，未读取任何明文密钥。")
        try:
            raw = base64.b64decode(ciphertext[len(self._PREFIX):], validate=True)
            return self._transform(raw, decrypt=True).decode("utf-8")
        except ConfigError:
            raise
        except Exception:
            raise ConfigError("密钥解锁失败，请使用原来的 Windows 用户账户。") from None


PROVIDER_PRESETS = (
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": ""},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"id": "qwen", "name": "阿里云百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": ""},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": ""},
    {"id": "ollama", "name": "本地 Ollama", "base_url": "http://127.0.0.1:11434/v1", "model": ""},
    {"id": "custom", "name": "自定义兼容接口", "base_url": "", "model": ""},
)

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_ID = re.compile(r"^[a-zA-Z0-9_-]{1,96}$")


def _text(value: Any, label: str, *, maximum: int = 256, empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label}必须是文字。")
    result = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in result):
        raise ConfigError(f"{label}不能包含换行或控制字符。")
    if len(result) > maximum or (not empty and not result):
        raise ConfigError(f"请填写有效的{label}。")
    return result


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ConfigError(f"{label}必须是开关值。")
    return value


def normalize_base_url(value: Any) -> str:
    """Accept OpenAI-compatible origins/paths, correcting pasted endpoint suffixes."""
    address = _text(value, "Base URL", maximum=2048, empty=False)
    if any(character.isspace() for character in address) or "\\" in address:
        raise ConfigError("Base URL 不能包含空格或反斜杠。")
    try:
        parsed = urlsplit(address)
        if (parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in address or "#" in address):
            raise ValueError
        _ = parsed.port
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/models"):
            if path.lower().endswith(suffix):
                path = path[:-len(suffix)].rstrip("/")
                break
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, "", ""))
    except ValueError:
        raise ConfigError("请填写 http:// 或 https:// 开头的接口地址，不要包含账户、密码、查询参数或片段。") from None


def _key_hint(key: str) -> str:
    # Short test/local tokens must not be disclosed in their entirety.
    return "••••" + (key[-4:] if len(key) > 4 else "") if key else ""


class ConfigStore:
    def __init__(self, root: Path | str, *, codec: SecretCodec | None = None) -> None:
        self.root = Path(root).resolve()
        self.directory = self.root / "studio_data"
        self.path = self.directory / "config.json"
        self.codec = codec if codec is not None else DPAPICodec()
        with _LOCKS_GUARD:
            self._thread_lock = _LOCKS.setdefault(os.path.normcase(str(self.path)), threading.RLock())

    @contextmanager
    def _locked(self):
        with self._thread_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle = (self.directory / ".config.lock").open("a+b")
            acquired = False
            try:
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0")
                    handle.flush()
                deadline = time.monotonic() + 10
                while not acquired:
                    handle.seek(0)
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise ConfigError("配置正在由另一个操作保存，请稍后重试。") from None
                        time.sleep(0.05)
                yield
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    @staticmethod
    def _empty() -> dict:
        return {"version": 1, "active_model_id": "", "active_zep_id": "",
                "auto_zep": True, "models": [], "zep": []}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            if self.path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
                raise ValueError
            if type(data.get("auto_zep")) is not bool:
                raise ValueError
            for field in ("active_model_id", "active_zep_id"):
                if not isinstance(data.get(field), str):
                    raise ValueError
            for kind in ("models", "zep"):
                if not isinstance(data.get(kind), list):
                    raise ValueError
                seen = set()
                for item in data[kind]:
                    if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                            or not _ID.fullmatch(item["id"]) or item["id"] in seen
                            or type(item.get("enabled")) is not bool
                            or not isinstance(item.get("key_enc"), str)
                            or not isinstance(item.get("key_hint"), str)
                            or any(name in item for name in ("key", "api_key", "password"))):
                        raise ValueError
                    if item["key_hint"] and (not item["key_hint"].startswith("••••")
                                              or len(item["key_hint"]) not in {4, 8}):
                        raise ValueError
                    _text(item["key_hint"], "密钥提示", maximum=8)
                    seen.add(item["id"])
                    _text(item.get("name"), "配置名称", maximum=120, empty=False)
                    if kind == "models":
                        normalize_base_url(item.get("base_url"))
                        _text(item.get("model"), "模型名称")
                    else:
                        _text(item.get("group"), "项目分组", maximum=120)
            return data
        except (OSError, UnicodeError, ValueError, TypeError):
            raise ConfigError("配置文件格式无效或无法读取。原文件已保留，请先修复配置文件。") from None

    def _save(self, data: dict) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                             dir=self.directory, prefix=".config-", suffix=".tmp",
                                             delete=False) as handle:
                temporary = Path(handle.name)
                if os.name != "nt":
                    os.chmod(temporary, 0o600)
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise ConfigError("配置保存失败，原配置仍被保留。请检查目录写入权限。") from None
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _public_item(item: dict, kind: str) -> dict:
        fields = ("id", "name", "base_url", "model", "enabled") if kind == "models" else (
            "id", "name", "group", "enabled")
        result = {name: item[name] for name in fields}
        result.update(has_key=bool(item["key_enc"]), key_hint=item["key_hint"] if item["key_enc"] else "")
        return result

    def public(self) -> dict:
        with self._locked():
            data = self._load()
            return {"version": 1, "active_model_id": data["active_model_id"],
                    "active_zep_id": data["active_zep_id"], "auto_zep": data["auto_zep"],
                    "models": [self._public_item(item, "models") for item in data["models"]],
                    "zep": [self._public_item(item, "zep") for item in data["zep"]],
                    "presets": copy.deepcopy(list(PROVIDER_PRESETS))}

    @staticmethod
    def _selected_revision(data: dict) -> str:
        """Hash only selected runtime inputs; names/hints/inactive presets do not apply."""
        selected = {}
        for kind, active_field, fields in (
            ("models", "active_model_id", ("id", "base_url", "model", "enabled", "key_enc")),
            ("zep", "active_zep_id", ("id", "group", "enabled", "key_enc")),
        ):
            selected[active_field] = data[active_field]
            item = next((item for item in data[kind] if item["id"] == data[active_field]), None)
            selected[kind] = {field: item[field] for field in fields} if item else None
        encoded = json.dumps(selected, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def runtime_revision(self) -> str:
        """Public-safe configuration fingerprint, computed without decrypting keys."""
        with self._locked():
            return self._selected_revision(self._load())

    def runtime_selection(self, expected_revision: str | None = None) -> dict:
        """Backend-only atomic snapshot of both selected profiles and their revision."""
        with self._locked():
            data = self._load()
            revision = self._selected_revision(data)
            if expected_revision is not None and expected_revision != revision:
                raise ConfigError("所选配置已变化，本次请求未应用。请刷新后重新启用预设。")
            model = self._find(data, "models", data["active_model_id"])
            zep = self._find(data, "zep", data["active_zep_id"])
            if not model["enabled"] or not zep["enabled"]:
                raise ConfigError("所选配置已停用。")
            return {"revision": revision, "model": self._runtime_item(model, "models"),
                    "zep": self._runtime_item(zep, "zep")}

    def _snapshot(self) -> dict:
        """Internal encrypted rollback point, never a browser response."""
        with self._locked():
            return copy.deepcopy(self._load())

    def _restore(self, snapshot: dict) -> None:
        with self._locked():
            self._save(snapshot)

    @staticmethod
    def _find(data: dict, kind: str, identifier: Any) -> dict:
        if not isinstance(identifier, str) or not identifier:
            raise ConfigError("请先选择一组配置。")
        item = next((item for item in data[kind] if item["id"] == identifier), None)
        if item is None:
            raise ConfigError("所选配置不存在，可能已被删除，请刷新后重试。")
        return item

    def _prepare(self, payload: Any, kind: str, existing: dict | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ConfigError("配置内容格式不正确。")
        previous = existing or {}
        name = _text(payload.get("name", previous.get("name", "")), "配置名称", maximum=120, empty=False)
        result = {"id": previous.get("id") or ("model_" if kind == "models" else "zep_") + uuid.uuid4().hex,
                  "name": name, "enabled": _boolean(payload.get("enabled", previous.get("enabled", True)), "启用状态"),
                  "key_enc": previous.get("key_enc", ""), "key_hint": previous.get("key_hint", "")}
        if kind == "models":
            result["base_url"] = normalize_base_url(payload.get("base_url", previous.get("base_url", "")))
            result["model"] = _text(payload.get("model", previous.get("model", "")), "模型名称")
        else:
            result["group"] = _text(payload.get("group", previous.get("group", "")), "项目分组", maximum=120)
        clear_key = _boolean(payload.get("clear_key", False), "清除密钥")
        key = _text(payload.get("key", ""), "API Key", maximum=16384)
        if clear_key and key:
            raise ConfigError("不能同时填写新密钥和清除密钥。")
        if clear_key:
            result.update(key_enc="", key_hint="")
        elif key:
            try:
                encrypted = self.codec.encrypt(key)
                if not isinstance(encrypted, str) or not encrypted or encrypted == key:
                    raise ValueError
            except Exception:
                raise _SecretStorageError("密钥加密失败，未保存配置。") from None
            result.update(key_enc=encrypted, key_hint=_key_hint(key))
        return result

    def _save_item(self, payload: Any, kind: str) -> dict:
        if not isinstance(payload, dict):
            raise ConfigError("配置内容格式不正确。")
        with self._locked():
            data = self._load()
            existing = self._find(data, kind, payload["id"]) if payload.get("id") else None
            item = self._prepare(payload, kind, existing)
            if existing is not None:
                data[kind][data[kind].index(existing)] = item
            else:
                data[kind].append(item)
            # Disabling an active profile must never silently select another key.
            active_field = "active_model_id" if kind == "models" else "active_zep_id"
            if not item["enabled"] and data[active_field] == item["id"]:
                data[active_field] = ""
            self._save(data)
            return self._public_item(item, kind)

    def save_model(self, payload: dict) -> dict:
        return self._save_item(payload, "models")

    def save_zep(self, payload: dict) -> dict:
        return self._save_item(payload, "zep")

    def _delete(self, identifier: str, kind: str) -> bool:
        with self._locked():
            data = self._load()
            item = self._find(data, kind, identifier)
            data[kind].remove(item)
            active_field = "active_model_id" if kind == "models" else "active_zep_id"
            if data[active_field] == identifier:
                data[active_field] = ""
            self._save(data)
            return True

    def delete_model(self, identifier: str) -> bool:
        return self._delete(identifier, "models")

    def delete_zep(self, identifier: str) -> bool:
        return self._delete(identifier, "zep")

    def _activate(self, identifier: str, kind: str) -> dict:
        with self._locked():
            data = self._load()
            item = self._find(data, kind, identifier)
            if not item["enabled"]:
                raise ConfigError("请先启用这组配置。")
            if kind == "models" and not item["model"]:
                raise ConfigError("请先获取并选择模型，或手动填写模型名称。")
            if kind == "zep" and not item["key_enc"]:
                raise ConfigError("请先填写 Zep API Key。")
            data["active_model_id" if kind == "models" else "active_zep_id"] = identifier
            self._save(data)
            return self._public_item(item, kind)

    def activate_model(self, identifier: str) -> dict:
        return self._activate(identifier, "models")

    def activate_zep(self, identifier: str) -> dict:
        return self._activate(identifier, "zep")

    def set_auto_zep(self, enabled: bool) -> bool:
        enabled = _boolean(enabled, "自动轮换")
        with self._locked():
            data = self._load()
            data["auto_zep"] = enabled
            self._save(data)
        return enabled

    def _runtime_item(self, item: dict, kind: str) -> dict:
        result = self._public_item(item, kind)
        result.pop("has_key")
        result.pop("key_hint")
        try:
            result["key"] = self.codec.decrypt(item["key_enc"]) if item["key_enc"] else ""
            _text(result["key"], "API Key", maximum=16384)
        except Exception:
            raise ConfigError("密钥解锁失败，请重新保存密钥或使用原来的 Windows 用户账户。") from None
        return result

    def _runtime(self, identifier: str | None, kind: str) -> dict:
        with self._locked():
            data = self._load()
            active_field = "active_model_id" if kind == "models" else "active_zep_id"
            item = self._find(data, kind, identifier if identifier is not None else data[active_field])
            if not item["enabled"]:
                raise ConfigError("所选配置已停用。")
            return self._runtime_item(item, kind)

    def runtime_model(self, id: str | None = None) -> dict:
        return self._runtime(id, "models")

    def runtime_zep(self, id: str | None = None) -> dict:
        return self._runtime(id, "zep")

    def zep_candidates(self) -> list[dict]:
        with self._locked():
            data = self._load()
            items = [item for item in data["zep"] if item["enabled"] and item["key_enc"]]
            items.sort(key=lambda item: item["id"] != data["active_zep_id"])
            return [self._runtime_item(item, "zep") for item in items]

    @staticmethod
    def _read_env(path: Path) -> dict[str, str]:
        values = {}
        if not path.exists():
            return values
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$", raw)
            if not match:
                continue
            name, value = match.groups()
            value = value.strip()
            if value[:1] in {"'", '"'}:
                quote = value[0]
                end = value.rfind(quote)
                value = value[1:end] if end > 0 else value[1:]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            values[name] = value
        return values

    def import_legacy(self) -> dict:
        """Import once, deduplicating exact credentials; never alter the old files."""
        with self._locked():
            already_configured = self.path.exists()
            data = self._load()
            counts = {"models": 0, "zep": 0, "skipped": 0, "already_imported": False}
            if data.get("_legacy_imported") is True:
                counts["already_imported"] = True
                return counts
            original_model_id = data["active_model_id"]
            original_zep_id = data["active_zep_id"]
            try:
                env = self._read_env(self.root / ".env")
                legacy_path = self.root / "manager_config.json"
                legacy = json.loads(legacy_path.read_text(encoding="utf-8-sig")) if legacy_path.exists() else {}
                if not isinstance(legacy, dict):
                    raise ValueError
            except (OSError, UnicodeError, ValueError):
                raise ConfigError("旧配置无法读取。旧文件已保留，未进行迁移。") from None

            def add(payload: dict, kind: str) -> dict | None:
                try:
                    candidate = self._prepare(payload, kind)
                except _SecretStorageError:
                    raise
                except ConfigError:
                    counts["skipped"] += 1
                    return None
                key = _text(payload.get("key", ""), "API Key", maximum=16384)
                for present in data[kind]:
                    same_key = self._runtime_item(present, kind)["key"] == key
                    if same_key and (kind == "zep" or (
                            present["base_url"] == candidate["base_url"] and present["model"] == candidate["model"])):
                        return present
                data[kind].append(candidate)
                counts[kind] += 1
                return candidate

            models = legacy.get("keys", {})
            if isinstance(models, dict):
                for name, entry in models.items():
                    if not isinstance(entry, dict):
                        counts["skipped"] += 1
                        continue
                    item = add({"name": name, "base_url": entry.get("base_url", entry.get("base", "")),
                                "model": entry.get("model", ""), "key": entry.get("key", ""),
                                "enabled": entry.get("enabled", True)}, "models")
                    if item and name == legacy.get("provider") and not data["active_model_id"]:
                        data["active_model_id"] = item["id"]
            if env.get("LLM_BASE_URL"):
                item = add({"name": "当前模型（旧配置）", "base_url": env["LLM_BASE_URL"],
                            "model": env.get("LLM_MODEL_NAME", ""), "key": env.get("LLM_API_KEY", "")}, "models")
                if item and not original_model_id:
                    data["active_model_id"] = item["id"]
            profiles = legacy.get("zep_profiles", [])
            if isinstance(profiles, list):
                for entry in profiles:
                    if not isinstance(entry, dict):
                        counts["skipped"] += 1
                        continue
                    item = add({"name": entry.get("name", "旧 Zep 配置"), "key": entry.get("key", ""),
                                "enabled": entry.get("enabled", True), "group": entry.get("group", "")}, "zep")
                    if item and item["name"] == legacy.get("active_zep") and not data["active_zep_id"]:
                        data["active_zep_id"] = item["id"]
            if env.get("ZEP_API_KEY"):
                item = add({"name": "当前 Zep（旧配置）", "key": env["ZEP_API_KEY"]}, "zep")
                if item and not original_zep_id:
                    data["active_zep_id"] = item["id"]
            if not already_configured and type(legacy.get("auto_zep")) is bool:
                data["auto_zep"] = legacy["auto_zep"]
            data["_legacy_imported"] = True
            self._save(data)
            return counts
