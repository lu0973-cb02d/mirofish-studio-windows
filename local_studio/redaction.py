"""Credential-safe text, JSON and formatted log output for the local Studio.

The cache contains secrets only in memory. It refreshes on configuration file
changes and retains previously observed keys while the process is alive, since
an older interview can still be using a replaced/deleted preset.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, quote_plus


REDACTED = "[已隐藏]"
UNAVAILABLE = "[敏感信息检查暂不可用，详细信息已隐藏]"
_ENV_NAMES = {
    "LLM_API_KEY", "LLM_BOOST_API_KEY", "ZEP_API_KEY", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "GOOGLE_API_KEY",
    "GEMINI_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
    "XAI_API_KEY", "SILICONFLOW_API_KEY", "COHERE_API_KEY", "TOGETHER_API_KEY",
    "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_AD_TOKEN", "MIROFISH_ENGINE_TOKEN",
}
_SENSITIVE_NAMES = {
    "key", "keys", "keyenc", "ciphertext", "apikey", "apikeys", "token", "tokens",
    "accesstoken", "refreshtoken", "authorization", "proxyauthorization", "password",
    "passwd", "secret", "clientsecret", "credentials", "credential", "cookie",
    "setcookie", "privatekey", "secretaccesskey", "accesskeyid",
}
_TRACE_NAMES = {"traceback", "stacktrace", "excinfo", "exceptiontraceback"}
_LABEL = r"(?:x[-_]?api[-_ ]?key|api[-_ ]?key|proxy[-_ ]?authorization|authorization|access[-_ ]?token|refresh[-_ ]?token|client[-_ ]?secret|secret[-_ ]?key|password)"
_PREFIX = rf"\b{_LABEL}\b(?:\s+(?:provided|supplied|received))?[\"']?\s*[:=：]\s*"
_QUOTED_ASSIGNMENT = re.compile(rf"(?P<prefix>{_PREFIX})(?P<quote>[\"'])(?P<value>(?:\\.|(?!(?P=quote)).)*?)(?P=quote)", re.I | re.S)
_AUTH_SCHEME = re.compile(rf"({_PREFIX})(?:Bearer|Basic|Api-Key)\s+([^\s\"'<>;,{{}}\[\]]+)", re.I)
_BARE_ASSIGNMENT = re.compile(rf"({_PREFIX})(?!(?:Bearer|Basic|Api-Key)\s)([^\s\"'<>;,{{}}\[\]]+)", re.I)
_BEARER = re.compile(r"(\bBearer\s+)([^\s\"'<>;,{}\[\]]+)", re.I)
_KEY_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gsk_[A-Za-z0-9_-]{12,}|hf_[A-Za-z0-9]{16,})\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.RLock()


def _sensitive(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in _SENSITIVE_NAMES or "apikey" in normalized or normalized.endswith(("password", "privatekey", "clientsecret"))


def _config_secrets(root) -> tuple[set[str], bool]:
    if root is None:
        root = os.environ.get("MIROFISH_STUDIO_ROOT")
    if not root:
        return set(), True
    root = Path(root).resolve()
    path = root / "studio_data/config.json"
    identity = os.path.normcase(str(root))
    with _CACHE_LOCK:
        cached = _CACHE.setdefault(identity, {"stamp": None, "secrets": set(), "failed_until": 0.0})
        try:
            info = path.stat()
            stamp = (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)
        except FileNotFoundError:
            return set(cached["secrets"]), True
        except OSError:
            return set(cached["secrets"]), False
        if cached["stamp"] == stamp:
            return set(cached["secrets"]), True
        if time.monotonic() < cached["failed_until"]:
            return set(cached["secrets"]), False
        try:
            from .config_store import ConfigStore

            store = ConfigStore(root)
            snapshot = store._snapshot()
            found = set()
            for kind in ("models", "zep"):
                # The internal snapshot/runtime-item pair also covers disabled
                # profiles, which public runtime_* intentionally rejects.
                for item in snapshot[kind]:
                    key = store._runtime_item(item, kind).get("key")
                    if isinstance(key, str) and key:
                        found.add(key)
            cached["secrets"].update(found)
            cached.update(stamp=stamp, failed_until=0.0)
            return set(cached["secrets"]), True
        except Exception:
            # Never print the original decrypt/config error or return raw text
            # when the full configured credential set could not be checked.
            cached["failed_until"] = time.monotonic() + 0.5
            return set(cached["secrets"]), False


def _secret_snapshot(root, extra_secrets) -> tuple[tuple[str, ...], bool]:
    secrets, available = _config_secrets(root)
    secrets.update(value for name in _ENV_NAMES if (value := os.environ.get(name)))
    extra_secrets = extra_secrets or ()
    if isinstance(extra_secrets, str):
        extra_secrets = (extra_secrets,)
    secrets.update(value for value in extra_secrets if isinstance(value, str) and value)
    secrets.discard("local-no-key")
    variants = set(secrets)
    for secret in secrets:
        variants.update((json.dumps(secret, ensure_ascii=False)[1:-1], json.dumps(secret)[1:-1],
                         quote(secret, safe=""), quote_plus(secret, safe=""), html.escape(secret, quote=True)))
        encoded = quote(secret, safe="")
        variants.add(re.sub(r"%[0-9A-F]{2}", lambda match: match.group(0).lower(), encoded))
    return tuple(sorted(variants, key=len, reverse=True)), available


def _clean_text(text: str, secrets: tuple[str, ...], available: bool) -> str:
    if not available:
        return UNAVAILABLE
    text = _QUOTED_ASSIGNMENT.sub(lambda m: m["prefix"] + m["quote"] + REDACTED + m["quote"], text)
    text = _AUTH_SCHEME.sub(lambda m: m[1] + REDACTED, text)
    text = _BARE_ASSIGNMENT.sub(lambda m: m[1] + REDACTED, text)
    text = _BEARER.sub(lambda m: m[1] + REDACTED, text)
    text = _KEY_TOKEN.sub(REDACTED, text)
    text = _JWT.sub(REDACTED, text)
    for secret in secrets:
        if len(secret) >= 4:
            text = text.replace(secret, REDACTED)
        else:
            text = re.sub(r"(?<!\w)" + re.escape(secret) + r"(?!\w)", REDACTED, text)
    return text


def redact_text(text, *, root=None, extra_secrets=()) -> str:
    """Keep useful error wording, replacing known keys and credential syntax."""
    try:
        secrets, available = _secret_snapshot(root, extra_secrets)
        return _clean_text(str(text), secrets, available)
    except Exception:
        return UNAVAILABLE


def redact_payload(value, *, root=None, extra_secrets=(), strip_traceback=True,
                   strip_sensitive_fields=True):
    """Return a JSON-safe copy, dropping credential and traceback fields.

    Use on provider/error responses. Credentials present in structured fields
    are also removed from other text in the same payload, including draft keys
    which have not been saved yet. Set ``strip_sensitive_fields=False`` for
    normal business data: ordinary key/tokens fields keep their shape and do
    not become additional secrets. Known credentials and credential syntax
    are always redacted. The original object is never changed.
    """
    extra = {extra_secrets} if isinstance(extra_secrets, str) else set(extra_secrets or ())
    collected = set()

    def collect(item, protected=False, depth=0):
        if depth > 40:
            return
        if isinstance(item, (dict, list, tuple)):
            if id(item) in collected:
                return
            collected.add(id(item))
        if isinstance(item, dict):
            for key, content in item.items():
                collect(content, protected or _sensitive(str(key)), depth + 1)
        elif isinstance(item, (list, tuple)):
            for content in item:
                collect(content, protected, depth + 1)
        elif protected and isinstance(item, str) and item:
            extra.add(item)

    try:
        if strip_sensitive_fields:
            collect(value)
        secrets, available = _secret_snapshot(root, extra)
        active = set()

        def clean(item, depth=0):
            if depth > 40:
                return REDACTED
            if isinstance(item, (dict, list, tuple)):
                if id(item) in active:
                    return REDACTED
                active.add(id(item))
                try:
                    if isinstance(item, dict):
                        result = {}
                        for key, content in item.items():
                            key = str(key)
                            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                            if (strip_sensitive_fields and _sensitive(key)) or (
                                    strip_traceback and normalized in _TRACE_NAMES):
                                continue
                            result[_clean_text(key, secrets, True)] = clean(content, depth + 1)
                        return result
                    return [clean(content, depth + 1) for content in item]
                finally:
                    active.remove(id(item))
            if isinstance(item, str):
                return _clean_text(item, secrets, available)
            if item is None or type(item) in (bool, int, float):
                return item
            return _clean_text(str(item), secrets, available)

        return clean(value)
    except Exception:
        return {"error": UNAVAILABLE}


class RedactingFormatter(logging.Formatter):
    """Redact the *formatted* result, including logging arguments and exc_info."""

    def __init__(self, *args, root=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.redaction_root = root

    def format(self, record):
        try:
            return redact_text(super().format(record), root=self.redaction_root)
        except Exception:
            return UNAVAILABLE


def clear_redaction_cache() -> None:
    """Tests/controlled teardown only; never needed when switching presets."""
    with _CACHE_LOCK:
        _CACHE.clear()
