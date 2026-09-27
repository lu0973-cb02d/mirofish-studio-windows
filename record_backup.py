"""Verified local snapshots of MiroFish project, simulation, and report records.

The archives intentionally exclude credentials and remote Zep graph contents.
SQLite databases are copied through SQLite's online backup API, so a snapshot
can be taken while a simulation is writing to them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath


BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "backend" / "uploads"
ARCHIVES = BASE / "record_backups"
FORMAT = "mirofish-records-v2"
LEGACY_FORMAT = "mirofish-records-v1"
BINDINGS_MEMBER = "studio/zep_bindings.json"
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_DEPTH = threading.local()


def _paths(root=None):
    base = Path(root).resolve() if root is not None else BASE.resolve()
    uploads = base / "backend/uploads" if root is not None else Path(UPLOADS)
    archives = base / "record_backups" if root is not None else Path(ARCHIVES)
    bindings = base / "studio_data/zep_bindings.json"
    if any(not p.resolve().is_relative_to(base) for p in (uploads, archives, bindings)):
        raise ValueError("备份目标必须位于 MiroFish 数据目录内")
    return base, uploads, archives, bindings


@contextmanager
def backup_guard(*, root=None, blocking=True):
    """Reentrant process/thread lock shared by manual backup, restore and auto."""
    _, _, archives, _ = _paths(root)
    archives.mkdir(parents=True, exist_ok=True)
    path = archives / ".backup.lock"
    identity = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(identity, threading.RLock())
    if not lock.acquire(blocking=blocking):
        yield False
        return
    depths = getattr(_LOCK_DEPTH, "depths", {})
    _LOCK_DEPTH.depths = depths
    if depths.get(identity, 0):
        depths[identity] += 1
        try:
            yield True
        finally:
            depths[identity] -= 1
            lock.release()
        return
    stream = None
    acquired = False
    try:
        stream = path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            acquired = True
        except OSError:
            if blocking:
                raise RuntimeError("另一个备份或恢复仍在进行，请稍后重试") from None
        if acquired:
            depths[identity] = 1
        yield acquired
    finally:
        if acquired and stream:
            depths.pop(identity, None)
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        if stream:
            stream.close()
        lock.release()


def _safe_relative(relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError("备份包含不安全路径")
    parts = PurePosixPath(relative).parts
    if (not parts or relative != PurePosixPath(relative).as_posix() or relative.startswith("/")
            or ".." in parts or "\\" in relative or ":" in relative or any(ord(c) < 32 for c in relative)):
        raise ValueError("备份包含不安全路径")
    for part in parts:
        if (part in {".", ".."} or part.endswith((".", " "))
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", part)):
            raise ValueError("备份包含不安全路径")
    return parts


def _record_files(uploads, *, include_wal=False):
    if not uploads.is_dir():
        return
    for source in sorted(uploads.rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        if not source.resolve().is_relative_to(uploads.resolve()):
            raise ValueError("数据目录包含指向外部的文件")
        relative = source.relative_to(uploads).as_posix()
        _safe_relative(relative)
        if source.name == ".gitkeep":
            continue
        if source.name.endswith(("-wal", "-shm")):
            database = source.with_name(source.name.rsplit("-", 1)[0])
            if database.is_file() and database.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                if source.name.endswith("-shm") or not include_wal:
                    continue
        yield source, relative


def record_fingerprint(*, root=None):
    """Detect changed records, including SQLite WAL, without reading secrets."""
    _, uploads, _, bindings = _paths(root)
    digest = hashlib.sha256()
    count = 0
    for source, relative in _record_files(uploads, include_wal=True):
        info = source.stat()
        digest.update(f"{relative}\0{info.st_size}\0{info.st_mtime_ns}\n".encode())
        count += 1
    if not count:
        return None
    if bindings.is_file():
        info = bindings.stat()
        digest.update(f"zep-bindings\0{info.st_size}\0{info.st_mtime_ns}".encode())
    return digest.hexdigest()


def _clean_bindings(value):
    """Whitelist ownership fields; never archive keys, config or health data."""
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Zep 图谱归属映射格式无效")
    result = {"version": 1, "graphs": {}, "resources": {}}
    for table in ("graphs", "resources"):
        if not isinstance(value.get(table), dict):
            raise ValueError("Zep 图谱归属映射格式无效")
        for identity, row in value[table].items():
            if not isinstance(identity, str) or not identity or len(identity) > 1000 or not isinstance(row, dict):
                raise ValueError("Zep 图谱归属映射格式无效")
            group, key_id, graph_id = row.get("group"), row.get("key_id"), row.get("graph_id")
            if (not isinstance(group, str) or not group.startswith(("group:", "key:"))
                    or not group.split(":", 1)[1] or len(group) > 1000
                    or not isinstance(key_id, str) or not key_id or len(key_id) > 200
                    or (graph_id is not None and (not isinstance(graph_id, str) or not graph_id))):
                raise ValueError("Zep 图谱归属映射格式无效")
            if group.startswith("key:") and group[4:] != key_id:
                raise ValueError("Zep 图谱归属映射中的配置标识不一致")
            if table == "graphs" and graph_id != identity:
                raise ValueError("Zep 图谱归属映射中的图谱标识不一致")
            if table == "resources" and (":" not in identity or identity.split(":", 1)[0] not in {"episode", "node", "edge", "batch"}):
                raise ValueError("Zep 图谱归属映射包含未知记录类型")
            result[table][identity] = {"group": group, "key_id": key_id, "graph_id": graph_id}
    for row in result["resources"].values():
        graph = result["graphs"].get(row["graph_id"])
        if graph and graph["group"] != row["group"]:
            raise ValueError("Zep 图谱与记录的账号归属不一致")
    return result


def _bindings_bytes(path):
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"version": 1, "graphs": {}, "resources": {}}
    return json.dumps(_clean_bindings(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    for attempt in range(3):
        try:
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)) as reader:
                with closing(sqlite3.connect(destination, timeout=15)) as writer:
                    reader.backup(writer, pages=1000, sleep=0.1)
                    result = writer.execute("PRAGMA quick_check").fetchone()
                    if result != ("ok",):
                        raise RuntimeError(f"数据库校验失败：{source.name}")
            return
        except sqlite3.Error:
            destination.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(0.5)


def create_backup(kind: str = "manual", *, root: str | Path | None = None) -> Path:
    """Create and verify a complete snapshot; never replace an existing archive."""
    if kind not in {"manual", "auto", "pre-restore"}:
        raise ValueError("无效备份类型")
    with backup_guard(root=root):
        return _create_backup(kind, root=root)


def _create_backup(kind, *, root=None):
    _, uploads, archives, bindings = _paths(root)
    if not uploads.is_dir():
        raise FileNotFoundError("找不到本地推演数据目录")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = archives / f"records-{kind}-{stamp}-{uuid.uuid4().hex[:8]}.zip"
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=archives) as temp_name:
        temp = Path(temp_name)
        draft = temp / "archive.zip"
        entries = []
        with zipfile.ZipFile(draft, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
            for source, relative in _record_files(uploads):
                readable = source
                if source.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    readable = temp / f"database-{len(entries)}.db"
                    _sqlite_snapshot(source, readable)
                else:
                    # Reading from a temporary copy avoids archiving half-written JSON.
                    readable = temp / f"file-{len(entries)}"
                    for attempt in range(3):
                        before = source.stat()
                        shutil.copy2(source, readable)
                        after = source.stat()
                        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                            break
                        if attempt == 2:
                            raise RuntimeError(f"文件正在变化，请稍后重试：{relative}")
                        time.sleep(0.2)
                size = readable.stat().st_size
                digest = _sha256_file(readable)
                archive.write(readable, f"records/{relative}")
                entries.append({"path": relative, "size": size, "sha256": digest})
                readable.unlink()
            mapping = _bindings_bytes(bindings)
            archive.writestr(BINDINGS_MEMBER, mapping)
            manifest = {"format": FORMAT, "created_at": datetime.now().astimezone().isoformat(), "kind": kind,
                        "file_count": len(entries), "entries": entries,
                        "zep_bindings": {"path": BINDINGS_MEMBER, "size": len(mapping), "sha256": hashlib.sha256(mapping).hexdigest()},
                        "note": "已含本地记录和 Zep 归属映射；云端图谱内容、模型/Zep 配置、API 密钥及冷却状态不在备份中。恢复记录不等于断点续跑。"}
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        verify_backup(draft)
        if target.exists():
            raise FileExistsError("备份文件名已存在，现有备份未被覆盖")
        os.replace(draft, target)
    return target


def verify_backup(path: Path) -> dict:
    """Reject damaged, foreign, duplicate, or path-traversal archives."""
    path = Path(path).resolve()
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(n.casefold() for n in names)) or names.count("manifest.json") != 1:
            raise ValueError("备份结构无效")
        manifest = json.loads(archive.read("manifest.json"))
        if (not isinstance(manifest, dict) or manifest.get("format") not in {FORMAT, LEGACY_FORMAT}
                or not isinstance(manifest.get("entries"), list)):
            raise ValueError("不是受支持的 MiroFish 记录备份")
        expected = {"manifest.json"}
        entry_names = set()
        for entry in manifest["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("备份校验清单无效")
            relative = entry.get("path", "")
            _safe_relative(relative)
            if relative.casefold() in entry_names:
                raise ValueError("备份清单包含重复路径")
            entry_names.add(relative.casefold())
            name = f"records/{relative}"
            expected.add(name)
            _verify_member(archive, name, entry)
        mapping = manifest.get("zep_bindings")
        if manifest["format"] == FORMAT:
            if not isinstance(mapping, dict) or mapping.get("path") != BINDINGS_MEMBER:
                raise ValueError("备份缺少受支持的 Zep 归属映射")
            expected.add(BINDINGS_MEMBER)
            _verify_member(archive, BINDINGS_MEMBER, mapping)
            value = json.loads(archive.read(BINDINGS_MEMBER))
            if value != _clean_bindings(value):
                raise ValueError("Zep 归属映射含有不允许备份的字段")
        elif mapping is not None:
            raise ValueError("旧版备份不支持附加配置文件")
        if set(names) != expected or manifest.get("file_count") != len(manifest["entries"]):
            raise ValueError("备份清单和内容不一致")
    return manifest


def _verify_member(archive, name, entry):
    if (type(entry.get("size")) is not int or entry["size"] < 0
            or not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
        raise ValueError("备份校验清单无效")
    info = archive.getinfo(name)
    if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.file_size != entry["size"]:
        raise ValueError("备份包含无效文件")
    digest = hashlib.sha256()
    size = 0
    with archive.open(info) as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
        raise ValueError("备份校验失败")


def _restore_notes(base, mapping):
    notes = ["模型/Zep 配置及 API 密钥不在备份内；云端图谱仍需可访问原项目的 Zep 配置。", "恢复记录不会自动续跑已中断的推演。"]
    if mapping is None:
        notes.insert(0, "此为旧版备份，未携带 Zep 图谱归属映射；已保留当前映射。")
        return notes, []
    key_ids = {row["key_id"] for table in ("graphs", "resources") for row in mapping[table].values()}
    try:
        from local_studio.config_store import ConfigStore
        configured = {row["id"] for row in ConfigStore(base).public()["zep"]}
    except Exception:
        notes.append("暂时无法核对原 Zep 配置是否存在，请在使用云端图谱前检查连接配置。")
        return notes, sorted(key_ids)
    missing = sorted(key_ids - configured)
    if missing:
        notes.append(f"有 {len(missing)} 个原 Zep 配置标识当前不存在；归属映射已保留，需恢复原配置或配置可访问原图谱的同组密钥。")
    else:
        notes.append("Zep 图谱归属映射已恢复；原配置标识可复用，云端可用性仍需连接验证。")
    return notes, missing


def restore_backup(path: Path, *, root: str | Path | None = None) -> tuple[dict, Path | None]:
    """Verify/stage records and bindings together. Caller must stop the engine."""
    with backup_guard(root=root):
        return _restore_backup(path, root=root)


def _restore_backup(path, *, root=None):
    path = Path(path).resolve()
    base, uploads, archives, bindings = _paths(root)
    manifest = verify_backup(path)
    uploads.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="restore-", dir=uploads.parent) as temp_name:
        temp = Path(temp_name)
        staging = temp / "uploads"
        staging.mkdir()
        mapping = None
        with zipfile.ZipFile(path) as archive:
            for entry in manifest["entries"]:
                destination = staging.joinpath(*_safe_relative(entry["path"]))
                if not destination.resolve().is_relative_to(staging.resolve()):
                    raise ValueError("解压目标超出推演目录")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(f"records/{entry['path']}") as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
            if manifest.get("zep_bindings"):
                mapping_bytes = archive.read(BINDINGS_MEMBER)
                mapping = _clean_bindings(json.loads(mapping_bytes))
                (temp / "zep_bindings.json").write_bytes(mapping_bytes)
        for entry in manifest["entries"]:
            destination = staging.joinpath(*_safe_relative(entry["path"]))
            if destination.stat().st_size != entry["size"] or _sha256_file(destination) != entry["sha256"]:
                raise ValueError("解压后校验失败，现有记录未更改")
        if mapping is not None and _sha256_file(temp / "zep_bindings.json") != manifest["zep_bindings"]["sha256"]:
            raise ValueError("Zep 归属映射解压后校验失败，现有记录未更改")
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        previous = archives / f"before-restore-{suffix}" if uploads.exists() else None
        old_mapping = bindings.read_bytes() if bindings.is_file() else None
        if mapping is not None and old_mapping is not None:
            protection_bytes = _bindings_bytes(bindings)
            protection = archives / f"before-restore-{suffix}.zep_bindings.json"
            protection.write_bytes(protection_bytes)
            if _sha256_file(protection) != hashlib.sha256(protection_bytes).hexdigest():
                raise ValueError("恢复前 Zep 归属映射保护副本校验失败")
        if previous is not None:
            os.replace(uploads, previous)
        records_swapped = False
        bindings_swapped = False
        try:
            os.replace(staging, uploads)
            records_swapped = True
            if mapping is not None:
                bindings.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp / "zep_bindings.json", bindings)
                bindings_swapped = True
        except Exception:
            if bindings_swapped:
                if old_mapping is None:
                    bindings.unlink(missing_ok=True)
                else:
                    rollback = temp / "old-bindings.json"
                    rollback.write_bytes(old_mapping)
                    os.replace(rollback, bindings)
            if records_swapped:
                os.replace(uploads, temp / "failed-uploads")
            if previous is not None and previous.exists():
                os.replace(previous, uploads)
            raise
    notes, missing = _restore_notes(base, mapping)
    return {**manifest, "restore_notes": notes, "missing_zep_profile_ids": missing,
            "zep_bindings_restored": mapping is not None}, previous


def list_backups(*, root: str | Path | None = None) -> list[Path]:
    _, _, archives, _ = _paths(root)
    return sorted(archives.glob("records-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True) if archives.exists() else []
