"""Verified, reversible updates of the MiroFish core (backend, locales, UI).

The installer ships one core. A *core bundle* is a newer, already-merged and
tested copy of that code published by this repository's release workflow. It is
applied without reinstalling, under these rules:

* The bundle is one zip whose ``MANIFEST.json`` lists every file with its size
  and SHA-256 and carries an Ed25519 signature (``MANIFEST.sig``). Nothing is
  extracted or run unless that signature verifies against the public key built
  into this application. A compromised download location cannot, by itself,
  make the app run foreign code.
* Extraction is defensive (no path escapes, links, duplicates, oversized or
  unexpected entries) and only touches ``backend/``, ``locales/``,
  ``frontend/dist/`` and ``source_info.json``. The Studio layer, the Python
  runtime and the installer are never replaced by a bundle.
* A bundle states what it needs (Studio API level, Python minor version and the
  exact set of locked Python dependencies). If the installed runtime does not
  match, it is refused: that case needs a new full installer.
* Installed versions live next to the user's data, so reinstalling the app does
  not lose them, and are verified again on every engine start. Anything that
  fails verification, or is not newer than the bundled core, is ignored in
  favour of the bundled core. Switching is a single atomic pointer change and
  can be rolled back.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import tomllib
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from . import ed25519

# Contract between a bundle's UI/backend and the Studio layer that launches it
# (the /studio-api routes and how the engine process is started). Raise it when
# that contract changes incompatibly; bundles declare the range they support.
STUDIO_API_LEVEL = 1

# The maintainer's Ed25519 public key (64 hex characters). While empty, core
# updates are disabled: nothing can be installed or used without a way to prove
# who published it. See docs/CORE_UPDATES.md.
UPDATE_PUBLIC_KEY_HEX = ""

RELEASES_URL = "https://api.github.com/repos/lu0973-cb02d/mirofish-studio-windows/releases"
CORE_TAG_PREFIX = "core-v"
ASSET_TEMPLATE = "mirofish-core-{version}.zip"
TRUSTED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")

BUNDLE_FORMAT = 1
MANIFEST_NAME = "MANIFEST.json"
SIGNATURE_NAME = "MANIFEST.sig"
PAYLOAD_PREFIX = "core/"
ALLOWED_PREFIXES = ("backend/", "locales/", "frontend/dist/")
ALLOWED_FILES = frozenset({"source_info.json"})
REQUIRED_FILES = ("backend/run.py", "backend/app/__init__.py", "locales/languages.json")

MAX_ZIP_BYTES = 150 * 1024 * 1024
MAX_FILES = 8000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
KEEP_PREVIOUS = 2

_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_WINDOWS_RESERVED = re.compile(r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?")


class CoreUpdateError(ValueError):
    """A safe, user-readable reason an update could not be used."""


def parse_version(text: Any) -> tuple[int, int, int]:
    if not isinstance(text, str) or not _VERSION.fullmatch(text):
        raise CoreUpdateError("核心版本号格式无效，应为 主.次.修订，例如 1.2.0。")
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(40):
            try:
                os.replace(handle.name, path)
                return
            except PermissionError:  # another handle still open on Windows
                if attempt == 39:
                    raise
                time.sleep(0.05)
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_parts(relative: str) -> tuple[str, ...]:
    """Reject anything that could resolve outside the destination or alias a name."""
    if not isinstance(relative, str) or not relative or relative.startswith("/") or "\\" in relative:
        raise CoreUpdateError("更新包包含不安全的路径。")
    if any(ord(char) < 32 for char in relative) or ":" in relative:
        raise CoreUpdateError("更新包包含不安全的路径。")
    parts = PurePosixPath(relative).parts
    # PurePosixPath quietly drops "." and empty segments. Insist on the canonical
    # spelling, or one file could be named two ways and later fail verification.
    if "/".join(parts) != relative:
        raise CoreUpdateError("更新包包含不安全的路径。")
    for part in parts:
        if part in {".", ".."} or part.endswith((".", " ")) or _WINDOWS_RESERVED.fullmatch(part):
            raise CoreUpdateError("更新包包含不安全的路径。")
    return parts


def deps_fingerprint(lock_text: str) -> str:
    """Hash the exact set of third-party packages a ``uv.lock`` pins.

    The project's own entry (editable/virtual source) is excluded so that
    bumping the application version does not change the fingerprint.
    """
    try:
        document = tomllib.loads(lock_text)
    except tomllib.TOMLDecodeError as error:
        raise CoreUpdateError("依赖锁文件无法读取。") from error
    pins = []
    for package in document.get("package", []):
        source = package.get("source") or {}
        if "editable" in source or "virtual" in source:
            continue
        pins.append(f"{str(package['name']).lower()}=={package['version']}")
    if not pins:
        raise CoreUpdateError("依赖锁文件中没有任何依赖。")
    return hashlib.sha256("\n".join(sorted(pins)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Selection:
    """Which copy of the core the engine should run."""

    code_root: Path
    version: str
    upstream_commit: str
    source: str  # "bundled" or "downloaded"
    frontend_root: Path | None = None
    notice: str = ""

    def public(self) -> dict[str, Any]:
        return {"version": self.version, "upstream_commit": self.upstream_commit,
                "source": self.source, "notice": self.notice}


@dataclass
class Release:
    version: str
    tag: str
    asset_name: str
    asset_url: str
    size: int
    digest: str = ""
    notes: str = ""
    published_at: str = ""

    def public(self) -> dict[str, Any]:
        return {"version": self.version, "tag": self.tag, "size": self.size,
                "notes": self.notes, "published_at": self.published_at}


@dataclass
class _Manifest:
    raw: bytes
    data: dict[str, Any]
    files: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return self.data["core_version"]


class CoreStore:
    """Installed core versions, the active pointer, and verification."""

    def __init__(self, data_root: Path | str, root: Path | str, *, public_key_hex: str | None = None):
        self.root = Path(root).resolve()
        self.base = Path(data_root).resolve() / "core"
        self.versions = self.base / "versions"
        self.incoming = self.base / "incoming"
        self.state_file = self.base / "state.json"
        key = UPDATE_PUBLIC_KEY_HEX if public_key_hex is None else public_key_hex
        self._public_key = bytes.fromhex(key) if re.fullmatch(r"[0-9a-fA-F]{64}", key or "") else None
        self.lock = threading.RLock()
        self._selection: Selection | None = None

    def selection(self) -> Selection:
        """The resolved core, cached: full verification is too heavy per request."""
        with self.lock:
            if self._selection is None:
                self._selection = self.resolve()
            return self._selection

    def invalidate(self) -> None:
        with self.lock:
            self._selection = None

    # ---- identity ---------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._public_key is not None

    def bundled(self) -> Selection:
        info: dict[str, Any] = {}
        try:
            info = json.loads((self.root / "source_info.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
        version = info.get("core_version")
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            version = "0.0.0"
        commit = info.get("commit") if isinstance(info.get("commit"), str) else ""
        return Selection(self.root, version, commit, "bundled")

    def installed_fingerprint(self) -> str | None:
        try:
            return deps_fingerprint((self.root / "backend" / "uv.lock").read_text(encoding="utf-8"))
        except (OSError, CoreUpdateError):
            return None

    # ---- state ------------------------------------------------------------
    def _state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        active = data.get("active") if isinstance(data.get("active"), str) and _VERSION.fullmatch(data["active"]) else None
        previous = [v for v in data.get("previous", []) if isinstance(v, str) and _VERSION.fullmatch(v)]
        return {"active": active, "previous": previous[-8:]}

    def _write_state(self, state: dict[str, Any]) -> None:
        _atomic_write(self.state_file, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def installed_versions(self) -> list[str]:
        try:
            names = [p.name for p in self.versions.iterdir() if p.is_dir() and _VERSION.fullmatch(p.name)]
        except OSError:
            return []
        return sorted(names, key=parse_version)

    # ---- manifest ---------------------------------------------------------
    def _read_manifest(self, raw: bytes, signature_text: str) -> _Manifest:
        if self._public_key is None:
            raise CoreUpdateError("此版本未内置更新签名公钥，核心更新功能未启用。")
        try:
            signature = bytes.fromhex(signature_text.strip())
        except ValueError:
            raise CoreUpdateError("更新包签名格式无效。") from None
        if not ed25519.verify(self._public_key, raw, signature):
            raise CoreUpdateError("更新包签名无效，已拒绝。请只从官方发布页获取更新。")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise CoreUpdateError("更新包清单无法读取。") from None
        return self._validate_manifest(raw, data)

    def _validate_manifest(self, raw: bytes, data: Any) -> _Manifest:
        if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
            raise CoreUpdateError("更新包格式不受支持，请先升级工作台。")
        parse_version(data.get("core_version"))
        requires = data.get("requires")
        if not isinstance(requires, dict):
            raise CoreUpdateError("更新包缺少兼容性声明。")
        levels = requires.get("studio_api")
        if (not isinstance(levels, list) or len(levels) != 2
                or not all(isinstance(n, int) and not isinstance(n, bool) for n in levels)
                or not levels[0] <= STUDIO_API_LEVEL <= levels[1]):
            raise CoreUpdateError("此更新需要更新版本的工作台，请先安装新的安装包。")
        if requires.get("python") != f"{sys.version_info[0]}.{sys.version_info[1]}":
            raise CoreUpdateError("此更新需要不同版本的 Python 运行环境，请安装新的完整安装包。")
        wanted = requires.get("deps_sha256")
        if not isinstance(wanted, str) or not _SHA256.fullmatch(wanted):
            raise CoreUpdateError("更新包缺少依赖校验信息。")
        installed = self.installed_fingerprint()
        if installed is None:
            raise CoreUpdateError("无法确认当前运行环境的依赖，不能安装核心更新。")
        if installed != wanted:
            raise CoreUpdateError("此更新需要不同的 Python 依赖，请安装新的完整安装包。")
        upstream = data.get("upstream")
        if not isinstance(upstream, dict) or not isinstance(upstream.get("commit"), str):
            raise CoreUpdateError("更新包缺少上游来源信息。")

        listed = data.get("files")
        if not isinstance(listed, list) or not 0 < len(listed) <= MAX_FILES:
            raise CoreUpdateError("更新包文件清单无效。")
        files: dict[str, dict[str, Any]] = {}
        folded: set[str] = set()
        total = 0
        for entry in listed:
            if not isinstance(entry, dict):
                raise CoreUpdateError("更新包文件清单无效。")
            path, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
            _safe_parts(path)
            if not (path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES)):
                raise CoreUpdateError("更新包包含不允许更新的文件。")
            if (not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= MAX_FILE_BYTES
                    or not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
                raise CoreUpdateError("更新包文件清单无效。")
            if path.casefold() in folded:
                raise CoreUpdateError("更新包包含重复文件。")
            folded.add(path.casefold())
            total += size
            if total > MAX_TOTAL_BYTES:
                raise CoreUpdateError("更新包解压后过大。")
            files[path] = {"size": size, "sha256": digest}
        missing = [name for name in REQUIRED_FILES if name not in files]
        if missing:
            raise CoreUpdateError(f"更新包缺少必需文件：{missing[0]}")
        return _Manifest(raw, data, files)

    # ---- installing ---------------------------------------------------------
    def install(self, bundle: Path | str) -> str:
        """Verify and stage a bundle; return its version. Does not activate it."""
        bundle = Path(bundle)
        with self.lock:
            if self._public_key is None:
                raise CoreUpdateError("此版本未内置更新签名公钥，核心更新功能未启用。")
            try:
                if bundle.stat().st_size > MAX_ZIP_BYTES:
                    raise CoreUpdateError("更新包过大。")
                archive = zipfile.ZipFile(bundle)
            except (OSError, zipfile.BadZipFile):
                raise CoreUpdateError("更新包无法打开，文件可能已损坏。") from None
            with archive:
                manifest = self._manifest_from_archive(archive)
                version = manifest.version
                floor = max([parse_version(self.bundled().version)] +
                            [parse_version(v) for v in self.installed_versions()])
                if parse_version(version) <= floor and version not in self.installed_versions():
                    raise CoreUpdateError(f"已有不低于 {version} 的核心版本，无需安装。")
                target = self.versions / version
                if target.exists():
                    try:
                        self.verify_installed(version)
                        return version  # already installed and intact
                    except CoreUpdateError:
                        shutil.rmtree(target, ignore_errors=True)  # damaged copy: replace it
                self.incoming.mkdir(parents=True, exist_ok=True)
                staging = self.incoming / f"{version}-{uuid.uuid4().hex[:8]}"
                try:
                    staging.mkdir()
                    self._extract(archive, manifest, staging)
                    self.versions.mkdir(parents=True, exist_ok=True)
                    os.replace(staging, target)
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
            return version

    def _manifest_from_archive(self, archive: zipfile.ZipFile) -> _Manifest:
        infos = archive.infolist()
        if not 0 < len(infos) <= MAX_FILES + 4:
            raise CoreUpdateError("更新包内容无效。")
        seen: set[str] = set()
        for info in infos:
            name = info.filename
            if info.flag_bits & 0x1:
                raise CoreUpdateError("更新包不应加密。")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise CoreUpdateError("更新包包含链接文件，已拒绝。")
            if name.endswith("/"):
                continue  # directory entries carry nothing
            _safe_parts(name)
            if name.casefold() in seen:
                raise CoreUpdateError("更新包包含重复文件。")
            seen.add(name.casefold())
            if name not in {MANIFEST_NAME, SIGNATURE_NAME} and not name.startswith(PAYLOAD_PREFIX):
                raise CoreUpdateError("更新包包含未声明的内容。")
            if info.file_size > MAX_FILE_BYTES:
                raise CoreUpdateError("更新包内含过大的文件。")
        try:
            raw_info, sig_info = archive.getinfo(MANIFEST_NAME), archive.getinfo(SIGNATURE_NAME)
        except KeyError:
            raise CoreUpdateError("更新包缺少清单或签名。") from None
        if raw_info.file_size > MAX_MANIFEST_BYTES or sig_info.file_size > 1024:
            raise CoreUpdateError("更新包清单过大。")
        manifest = self._read_manifest(archive.read(raw_info), archive.read(sig_info).decode("ascii", "replace"))
        declared = {PAYLOAD_PREFIX + path for path in manifest.files}
        present = {info.filename for info in infos if not info.filename.endswith("/")} - {MANIFEST_NAME, SIGNATURE_NAME}
        if declared != present:
            raise CoreUpdateError("更新包内容与签名清单不一致，已拒绝。")
        return manifest

    def _extract(self, archive: zipfile.ZipFile, manifest: _Manifest, destination: Path) -> None:
        for path, expected in manifest.files.items():
            target = destination.joinpath(*_safe_parts(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, written = hashlib.sha256(), 0
            with archive.open(PAYLOAD_PREFIX + path) as source, target.open("wb") as sink:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    written += len(chunk)
                    if written > expected["size"]:
                        raise CoreUpdateError("更新包文件大小与清单不符，已拒绝。")
                    digest.update(chunk)
                    sink.write(chunk)
            if written != expected["size"] or digest.hexdigest() != expected["sha256"]:
                raise CoreUpdateError("更新包文件校验失败，已拒绝。")
        _atomic_write(destination / MANIFEST_NAME, manifest.raw)
        signature = archive.read(SIGNATURE_NAME)
        _atomic_write(destination / SIGNATURE_NAME, signature)

    # ---- verifying what is already on disk ------------------------------------
    def verify_installed(self, version: str) -> _Manifest:
        parse_version(version)
        directory = self.versions / version
        try:
            raw = (directory / MANIFEST_NAME).read_bytes()
            signature = (directory / SIGNATURE_NAME).read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError):
            raise CoreUpdateError(f"核心 {version} 的清单缺失。") from None
        manifest = self._read_manifest(raw, signature)
        if manifest.version != version:
            raise CoreUpdateError(f"核心 {version} 的清单与目录不符。")
        expected = set(manifest.files) | {MANIFEST_NAME, SIGNATURE_NAME}
        found: set[str] = set()
        for current, directories, names in os.walk(directory, followlinks=False):
            for entry in directories:
                if (Path(current) / entry).is_symlink():
                    raise CoreUpdateError(f"核心 {version} 含有链接目录，已忽略。")
            for name in names:
                path = Path(current) / name
                if path.is_symlink():
                    raise CoreUpdateError(f"核心 {version} 含有链接文件，已忽略。")
                found.add(path.relative_to(directory).as_posix())
        if found != expected:
            raise CoreUpdateError(f"核心 {version} 的文件与清单不一致，已忽略。")
        for path, entry in manifest.files.items():
            target = directory.joinpath(*path.split("/"))
            if target.stat().st_size != entry["size"] or _sha256_file(target) != entry["sha256"]:
                raise CoreUpdateError(f"核心 {version} 的文件已被改动，已忽略。")
        return manifest

    # ---- choosing and switching ---------------------------------------------
    def resolve(self) -> Selection:
        """The core the engine must run, falling back to the bundled one."""
        bundled = self.bundled()
        with self.lock:
            active = self._state()["active"]
            if not active:
                return bundled
            try:
                manifest = self.verify_installed(active)
            except (CoreUpdateError, OSError) as error:
                return Selection(bundled.code_root, bundled.version, bundled.upstream_commit, "bundled",
                                 notice=f"已安装的核心更新未通过校验，正在使用内置核心：{error}")
            if parse_version(active) <= parse_version(bundled.version):
                return Selection(bundled.code_root, bundled.version, bundled.upstream_commit, "bundled",
                                 notice=f"内置核心 {bundled.version} 不低于已安装的 {active}，已使用内置核心。")
            directory = self.versions / active
            dist = directory / "frontend" / "dist"
            return Selection(directory, active, manifest.data["upstream"]["commit"], "downloaded",
                             frontend_root=dist if (dist / "index.html").is_file() else None)

    def activate(self, version: str) -> Selection:
        with self.lock:
            if not self.enabled:
                raise CoreUpdateError("此版本未内置更新签名公钥，核心更新功能未启用。")
            self.verify_installed(version)
            if parse_version(version) <= parse_version(self.bundled().version):
                raise CoreUpdateError(f"版本 {version} 不高于内置核心 {self.bundled().version}。")
            state = self._state()
            if state["active"] == version:
                self.invalidate()
                return self.resolve()
            if state["active"]:
                state["previous"].append(state["active"])
            state["active"] = version
            self._write_state(state)
            self.invalidate()
            return self.resolve()

    def rollback(self) -> Selection:
        """Return to the previous valid core, or to the bundled one."""
        with self.lock:
            state = self._state()
            if not state["active"]:
                raise CoreUpdateError("当前已在使用内置核心，没有可回退的版本。")
            target = None
            while state["previous"]:
                candidate = state["previous"].pop()
                try:
                    self.verify_installed(candidate)
                except (CoreUpdateError, OSError):
                    continue
                if parse_version(candidate) > parse_version(self.bundled().version):
                    target = candidate
                    break
            state["active"] = target
            self._write_state(state)
            self.invalidate()
            return self.resolve()

    def prune(self, keep: int = KEEP_PREVIOUS) -> list[str]:
        """Delete installed versions that are neither active nor recent history."""
        with self.lock:
            state = self._state()
            retained = set(state["previous"][-keep:]) | ({state["active"]} if state["active"] else set())
            removed = []
            for version in self.installed_versions():
                if version not in retained:
                    shutil.rmtree(self.versions / version, ignore_errors=True)
                    removed.append(version)
            if self.incoming.is_dir():
                for leftover in self.incoming.iterdir():
                    if time.time() - leftover.stat().st_mtime > 3600:
                        shutil.rmtree(leftover, ignore_errors=True) if leftover.is_dir() else leftover.unlink(missing_ok=True)
            return removed

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self._state()

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Put the active/previous pointers back after a failed switch."""
        with self.lock:
            self._write_state({"active": snapshot.get("active"), "previous": list(snapshot.get("previous", []))})
            self.invalidate()

    def status(self) -> dict[str, Any]:
        selection = self.selection()
        state = self._state()
        return {"enabled": self.enabled, "running": selection.public(), "bundled": self.bundled().public(),
                "active": state["active"], "installed": self.installed_versions(),
                "can_rollback": bool(state["active"]), "studio_api_level": STUDIO_API_LEVEL}


# ---- finding and downloading releases ------------------------------------------------

def _trusted_url(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return parts.scheme in {"http", "https"}  # loopback: used by tests only
    return parts.scheme == "https" and any(host == s or host.endswith("." + s) for s in TRUSTED_HOST_SUFFIXES)


class ReleaseSource:
    """Looks for ``core-v*`` releases and downloads their bundle."""

    def __init__(self, releases_url: str = RELEASES_URL, *, timeout: float = 20.0,
                 client_factory: Callable[[], httpx.Client] | None = None):
        self.releases_url = releases_url
        self._factory = client_factory or (lambda: httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "MiroFish-Studio"}))

    def latest(self) -> Release | None:
        if not _trusted_url(self.releases_url):
            raise CoreUpdateError("更新地址不受信任。")
        try:
            with self._factory() as client:
                response = client.get(self.releases_url, params={"per_page": 30})
                if response.status_code == 403 and "rate limit" in response.text.lower():
                    raise CoreUpdateError("检查更新过于频繁，请稍后再试。")
                response.raise_for_status()
                releases = response.json()
        except CoreUpdateError:
            raise  # a ValueError subclass: do not let the handler below rewrite it
        except httpx.HTTPError:
            raise CoreUpdateError("无法连接更新服务器，请检查网络后重试，或使用「导入更新包」。") from None
        except ValueError:
            raise CoreUpdateError("更新服务器返回了无法识别的内容。") from None
        best: Release | None = None
        for item in releases if isinstance(releases, list) else []:
            tag = item.get("tag_name") if isinstance(item, dict) else None
            if (not isinstance(tag, str) or not tag.startswith(CORE_TAG_PREFIX)
                    or item.get("draft") or item.get("prerelease")):
                continue
            version = tag[len(CORE_TAG_PREFIX):]
            if not _VERSION.fullmatch(version):
                continue
            wanted = ASSET_TEMPLATE.format(version=version)
            asset = next((a for a in item.get("assets", []) if isinstance(a, dict) and a.get("name") == wanted), None)
            if not asset or not isinstance(asset.get("browser_download_url"), str):
                continue
            digest = asset.get("digest") if isinstance(asset.get("digest"), str) else ""
            candidate = Release(version, tag, wanted, asset["browser_download_url"],
                                int(asset.get("size") or 0), digest.removeprefix("sha256:"),
                                str(item.get("body") or "")[:4000], str(item.get("published_at") or ""))
            if best is None or parse_version(candidate.version) > parse_version(best.version):
                best = candidate
        return best

    def download(self, release: Release, destination: Path,
                 progress: Callable[[int, int], None] | None = None) -> Path:
        if not _trusted_url(release.asset_url):
            raise CoreUpdateError("下载地址不受信任。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest, received = hashlib.sha256(), 0
        try:
            with self._factory() as client, client.stream("GET", release.asset_url) as response:
                response.raise_for_status()
                if not _trusted_url(str(response.url)):
                    raise CoreUpdateError("下载被重定向到不受信任的地址，已中止。")
                with destination.open("wb") as sink:
                    for chunk in response.iter_bytes(1024 * 256):
                        received += len(chunk)
                        if received > MAX_ZIP_BYTES:
                            raise CoreUpdateError("更新包过大，已中止下载。")
                        digest.update(chunk)
                        sink.write(chunk)
                        if progress:
                            progress(received, release.size)
        except httpx.HTTPError:
            destination.unlink(missing_ok=True)
            raise CoreUpdateError("下载更新包失败，请检查网络后重试。") from None
        except CoreUpdateError:
            destination.unlink(missing_ok=True)
            raise
        if release.digest and release.digest != digest.hexdigest():
            destination.unlink(missing_ok=True)
            raise CoreUpdateError("下载的文件与发布页记录的校验值不一致，已丢弃。")
        return destination


def check_for_update(store: CoreStore, source: ReleaseSource) -> tuple[dict[str, Any], Release | None]:
    """Return the answer for the UI and, when newer, the release to install."""
    release = source.latest()
    running = store.resolve().version
    if release is None or parse_version(release.version) <= parse_version(running):
        return {"available": False, "current": running, "latest": release.version if release else None}, None
    return {"available": True, "current": running, "latest": release.version,
            "release": release.public(), "can_install": store.enabled}, release


def download_and_install(store: CoreStore, source: ReleaseSource, release: Release) -> str:
    store.incoming.mkdir(parents=True, exist_ok=True)
    bundle = store.incoming / f"download-{uuid.uuid4().hex[:8]}.zip"
    try:
        source.download(release, bundle)
        version = store.install(bundle)
    finally:
        bundle.unlink(missing_ok=True)
    if version != release.version:
        raise CoreUpdateError("下载的更新包版本与发布页不一致，已拒绝使用。")
    return version
