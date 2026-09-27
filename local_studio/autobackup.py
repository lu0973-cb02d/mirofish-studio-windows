"""Controller-owned automatic snapshots, with no hidden external scheduler."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
import zipfile
from pathlib import Path

import record_backup


class AutoBackup:
    """Back up changed records every 15 minutes; retain only 20 auto archives.

    Manual and pre-restore archives are never pruned. The shared record_backup
    lock also covers fingerprint comparison, publishing and pruning, so another
    controller instance cannot produce a duplicate snapshot for the same state.
    """

    def __init__(self, root: str | Path, interval_seconds: float = 900, retain: int = 20):
        if interval_seconds <= 0 or type(retain) is not int or retain < 1:
            raise ValueError("自动备份间隔和保留数量必须大于零")
        self.root = Path(root).resolve()
        self.interval_seconds = float(interval_seconds)
        self.retain = retain
        self.state_file = self.root / "studio_data/autobackup_state.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state = {"enabled": False, "interval_seconds": self.interval_seconds, "retain": retain,
                       "last_backup": None, "last_backup_at": None, "last_error": None,
                       "last_check_at": None, "next_check_at": None, "outcome": "not_started"}

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._state["enabled"] = True
            self._thread = threading.Thread(target=self._loop, name="mirofish-auto-backup", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5) -> bool:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0, timeout))
        stopped = thread is None or not thread.is_alive()
        with self._lock:
            if stopped:
                self._state.update(enabled=False, next_check_at=None)
        return stopped

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                self.run_once()
                with self._lock:
                    self._state["next_check_at"] = time.time() + self.interval_seconds
                self._stop.wait(self.interval_seconds)
        finally:
            with self._lock:
                self._state.update(enabled=False, next_check_at=None)

    def _read_state(self) -> dict:
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_state(self, value: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_name("autobackup-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_file)
        finally:
            temporary.unlink(missing_ok=True)

    def _prune(self) -> int:
        archives = (self.root / "record_backups").resolve()
        automatic = []
        for path in archives.glob("records-auto-*.zip"):
            if not path.is_file() or path.is_symlink() or path.resolve().parent != archives:
                continue
            try:
                with zipfile.ZipFile(path) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                if isinstance(manifest, dict) and manifest.get("kind") == "auto" and manifest.get("format") in {record_backup.FORMAT, record_backup.LEGACY_FORMAT}:
                    automatic.append(path)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                # Unknown/damaged user files are not silently erased.
                continue
        automatic.sort(key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
        removed = 0
        for path in automatic[self.retain:]:
            path.unlink()
            removed += 1
        return removed

    def run_once(self) -> dict:
        """One non-blocking check; useful for controller startup and tests."""
        now = time.time()
        with self._lock:
            self._state.update(last_check_at=now, last_error=None)
        try:
            with record_backup.backup_guard(root=self.root, blocking=False) as acquired:
                if not acquired:
                    outcome = "busy"
                else:
                    previous = self._read_state()
                    with self._lock:
                        self._state.update(last_backup=previous.get("last_backup"), last_backup_at=previous.get("last_backup_at"))
                    fingerprint = record_backup.record_fingerprint(root=self.root)
                    old_name = previous.get("last_backup")
                    prior_exists = (isinstance(old_name, str) and Path(old_name).name == old_name
                                    and (self.root / "record_backups" / old_name).is_file())
                    if fingerprint is None:
                        outcome = "empty"
                    elif fingerprint == previous.get("fingerprint") and prior_exists:
                        outcome = "unchanged"
                    else:
                        path = record_backup.create_backup("auto", root=self.root)
                        # Record the pre-snapshot marker. Changes during the
                        # snapshot then cause a fresh backup on the next check.
                        previous = {"fingerprint": fingerprint, "last_backup": path.name, "last_backup_at": time.time()}
                        self._write_state(previous)
                        with self._lock:
                            self._state.update(last_backup=path.name, last_backup_at=previous["last_backup_at"])
                        outcome = "created"
                    self._prune()
        except Exception:
            # Do not echo paths, document contents or arbitrary exception text
            # into the controller status API. Published backups stay intact.
            with self._lock:
                self._state.update(last_error="自动备份未完成，已有备份仍保留；稍后将再次检查。", outcome="error")
            return self.status()
        with self._lock:
            self._state["outcome"] = outcome
        return self.status()
