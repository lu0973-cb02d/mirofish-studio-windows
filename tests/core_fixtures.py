"""Build genuine and hostile core bundles for tests (see local_studio.core_update)."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

from local_studio import core_update, ed25519

LOCK_TEXT = """version = 1
[[package]]
name = "mirofish-backend"
version = "0.1.0"
source = { editable = "." }
[[package]]
name = "flask"
version = "3.1.2"
source = { registry = "https://pypi.org/simple" }
[[package]]
name = "openai"
version = "1.2.3"
source = { registry = "https://pypi.org/simple" }
"""
SEED = bytes(range(1, 33))
OTHER_SEED = bytes(range(101, 133))
PUBLIC_HEX = ed25519.public_key(SEED).hex()


class Member:
    """One zip entry that a test may still alter before it is written."""

    def __init__(self, name: str, data: bytes = b"", *, mode: int = 0o100644, flags: int = 0):
        self.name, self.data, self.mode, self.flags = name, data, mode, flags


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_files(version: str) -> dict[str, bytes]:
    return {
        "backend/run.py": f"print('core {version}')\n".encode(),
        "backend/app/__init__.py": b"",
        "backend/uv.lock": LOCK_TEXT.encode(),
        "locales/languages.json": b"{}",
        "frontend/dist/index.html": f"<html>core {version}</html>".encode(),
        "source_info.json": json.dumps({"commit": "abc"}).encode(),
    }


class App:
    """A fake installed application plus a store bound to the test key."""

    def __init__(self, tmp_path: Path, *, bundled_version: str = "1.1.0", public_hex: str | None = PUBLIC_HEX):
        self.tmp = tmp_path
        self.root = tmp_path / "app"
        self.data_root = tmp_path / "data"
        (self.root / "backend").mkdir(parents=True)
        (self.root / "backend" / "uv.lock").write_text(LOCK_TEXT, encoding="utf-8")
        (self.root / "backend" / "run.py").write_text("print('bundled')\n", encoding="utf-8")
        self.set_bundled(bundled_version)
        self.public_hex = public_hex
        self.store = core_update.CoreStore(self.data_root, self.root, public_key_hex=public_hex)

    def set_bundled(self, version: str) -> None:
        (self.root / "source_info.json").write_text(
            json.dumps({"core_version": version, "commit": "bundled-commit"}), encoding="utf-8")

    def bundle(self, version: str = "1.1.1", *, files: dict | None = None, requires: dict | None = None,
               manifest: dict | None = None, seed: bytes = SEED, signature: str | None = None,
               mutate=None, name: str | None = None) -> Path:
        payload = {**default_files(version), **(files or {})}
        data = {
            "format": core_update.BUNDLE_FORMAT, "core_version": version, "built_at": "2026-10-01T00:00:00+00:00",
            "upstream": {"repo": "https://example.invalid/up", "commit": "c0ffee"}, "notes": f"notes {version}",
            "requires": {"studio_api": [core_update.STUDIO_API_LEVEL, core_update.STUDIO_API_LEVEL],
                         "python": f"{__import__('sys').version_info[0]}.{__import__('sys').version_info[1]}",
                         "deps_sha256": core_update.deps_fingerprint(LOCK_TEXT), **(requires or {})},
            "files": [{"path": p, "size": len(d), "sha256": sha256(d)} for p, d in sorted(payload.items())],
        }
        data.update(manifest or {})
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        sig = signature if signature is not None else ed25519.sign(seed, raw).hex()
        members = [Member(core_update.MANIFEST_NAME, raw), Member(core_update.SIGNATURE_NAME, sig.encode())]
        members += [Member(core_update.PAYLOAD_PREFIX + p, d) for p, d in sorted(payload.items())]
        if mutate:
            members = mutate(members) or members
        path = self.tmp / (name or f"bundle-{version}-{len(list(self.tmp.glob('bundle-*')))}.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in members:
                info = zipfile.ZipInfo(member.name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = member.mode << 16
                archive.writestr(info, member.data)
        self._patch_flags(path, {m.name: m.flags for m in members if m.flags})
        return path

    @staticmethod
    def _patch_flags(path: Path, flags: dict[str, int]) -> None:
        """zipfile resets general-purpose flags on write; set them in the central directory."""
        if not flags:
            return
        raw = bytearray(path.read_bytes())
        offset = raw.find(b"PK\x01\x02")
        while offset != -1:
            name_length = int.from_bytes(raw[offset + 28:offset + 30], "little")
            name = bytes(raw[offset + 46:offset + 46 + name_length]).decode()
            if name in flags:
                current = int.from_bytes(raw[offset + 8:offset + 10], "little")
                raw[offset + 8:offset + 10] = (current | flags[name]).to_bytes(2, "little")
            offset = raw.find(b"PK\x01\x02", offset + 4)
        path.write_bytes(bytes(raw))


def find(members, name):
    return next(m for m in members if m.name == name)


def replace_data(name, data):
    def mutate(members):
        find(members, name).data = data
    return mutate


def add_member(member):
    def mutate(members):
        members.append(member)
    return mutate


def drop_member(name):
    def mutate(members):
        return [m for m in members if m.name != name]
    return mutate


def symlink(name, target=b"/etc/passwd"):
    return Member(name, target, mode=stat.S_IFLNK | 0o777)
