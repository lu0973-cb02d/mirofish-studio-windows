"""HTTP surface for core updates and the switch procedure behind it."""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from . import core_update
from .core_update import CoreStore, CoreUpdateError, ReleaseSource, Selection

HEALTHY_WAIT_SECONDS = 120.0


def _await_healthy(engine, selection: Selection, *, timeout: float, sleep: Callable[[float], None] = time.sleep) -> None:
    """Wait for the restarted engine to serve the core we asked for."""
    deadline = time.monotonic() + timeout
    while True:
        state = engine.status()
        if state.get("healthy"):
            running = state.get("core_version")
            if running and running != selection.version:
                raise CoreUpdateError(f"引擎启动了核心 {running}，与预期的 {selection.version} 不符。")
            return
        if state.get("state") in {"stopped", "error"}:
            raise CoreUpdateError("引擎在切换核心后没有启动成功。")
        if time.monotonic() >= deadline:
            raise CoreUpdateError("引擎在切换核心后长时间没有就绪。")
        sleep(0.5)


def switch_core(core: CoreStore, engine, change: Callable[[], Selection], *, data_root: Path,
                backup: Callable[..., Any] | None = None, wait: float = HEALTHY_WAIT_SECONDS,
                sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Apply ``change`` (activate or roll back) and make the running engine follow.

    Records are backed up first when an engine is running; a core that fails to
    come up is undone automatically and the previous one is started again.
    """
    with engine.lock:
        engine.ensure_idle()
        running = bool(engine.status().get("owned"))
        if running and backup is not None:
            backup("pre-update", root=data_root)
        snapshot = core.snapshot()
        selection = change()
        if not running:
            core.prune()
            return {"running": selection.public(), "restarted": False}
        try:
            engine.stop()
            engine.start()
            _await_healthy(engine, selection, timeout=wait, sleep=sleep)
        except Exception as failure:  # the new core did not come up: go back
            core.restore(snapshot)
            previous = core.resolve()
            try:
                engine.stop(force=True)
                engine.start()
                _await_healthy(engine, previous, timeout=wait, sleep=sleep)
            except Exception:
                raise CoreUpdateError("切换核心失败，且旧版本也未能自动启动。已恢复原来的选择，请在工作台手动重启引擎。") from failure
            raise CoreUpdateError("新的核心没有正常启动，已自动恢复到原来的版本。") from failure
        core.prune()
        return {"running": selection.public(), "restarted": True}


def create_blueprint(core: CoreStore, engine, data_root: Path, *,
                     source: ReleaseSource | None = None, backup: Callable[..., Any] | None = None) -> Blueprint:
    blueprint = Blueprint("core", __name__)
    cache: dict[str, Any] = {"check": None, "release": None}
    source = source or ReleaseSource()
    if backup is None:
        import record_backup
        backup = record_backup.create_backup

    def ok(data=None):
        return jsonify(success=True, data=data)

    def version_from_request() -> str:
        value = request.get_json(silent=True)
        version = value.get("version") if isinstance(value, dict) else None
        core_update.parse_version(version)
        return version

    @blueprint.get("/studio-api/core")
    def status():
        data = core.status()
        data["engine_core_version"] = engine.status().get("core_version") or ""
        data["notice"] = getattr(engine, "core_notice", "") or data["running"].get("notice", "")
        # A check made against an older running core says nothing about now.
        check = cache["check"]
        data["last_check"] = check if check and check.get("current") == data["running"]["version"] else None
        return ok(data)

    @blueprint.post("/studio-api/core/check")
    def check():
        result, release = core_update.check_for_update(core, source)
        cache["check"], cache["release"] = result, release
        return ok(result)

    @blueprint.post("/studio-api/core/install")
    def install():
        version = version_from_request()
        release = cache["release"]
        if release is None or release.version != version:
            raise CoreUpdateError("请先检查更新，再安装。")
        installed = core_update.download_and_install(core, source, release)
        return ok({"installed": installed})

    @blueprint.post("/studio-api/core/import")
    def import_bundle():
        upload = request.files.get("bundle")
        if upload is None or not upload.filename:
            raise CoreUpdateError("请选择更新包文件。")
        core.incoming.mkdir(parents=True, exist_ok=True)
        path = core.incoming / f"import-{uuid.uuid4().hex[:8]}.zip"
        try:
            upload.save(path)
            installed = core.install(path)
        finally:
            path.unlink(missing_ok=True)
        return ok({"installed": installed})

    @blueprint.post("/studio-api/core/activate")
    def activate():
        version = version_from_request()
        return ok(switch_core(core, engine, lambda: core.activate(version), data_root=data_root, backup=backup))

    @blueprint.post("/studio-api/core/rollback")
    def rollback():
        return ok(switch_core(core, engine, core.rollback, data_root=data_root, backup=backup))

    return blueprint
