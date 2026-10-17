"""Switching the running engine to another core, and undoing it when it fails."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core_fixtures import App
from local_studio import core_routes
from local_studio.core_update import CoreUpdateError
from local_studio.engine import EngineError, EngineManager


class FakeEngine:
    """Behaves like EngineManager.start(): it asks the core store what to run."""

    def __init__(self, core, *, running=True):
        self.core = core
        self.lock = threading.RLock()
        self.running = running
        self.busy = False
        self.calls = []
        self.core_version = core.resolve().version if running else ""
        self.broken = set()      # core versions that fail to start
        self.lying = {}          # core version -> version the engine claims to run
        self.hang = False        # start but never become healthy
        self.core_notice = ""

    def status(self):
        if not self.running:
            return {"state": "stopped", "healthy": False, "owned": False}
        if self.hang:
            return {"state": "starting", "healthy": False, "owned": True}
        return {"state": "running", "healthy": True, "owned": True, "core_version": self.core_version}

    def ensure_idle(self):
        self.calls.append("ensure_idle")
        if self.busy:
            raise EngineError("当前有任务正在执行。")

    def stop(self, force=False):
        self.calls.append("stop(force)" if force else "stop")
        self.running = False

    def start(self):
        selection = self.core.resolve()
        self.calls.append(f"start:{selection.version}")
        if selection.version in self.broken:
            self.running = False
            raise EngineError("引擎启动失败")
        self.running = True
        self.core_version = self.lying.get(selection.version, selection.version)


@pytest.fixture
def app(tmp_path):
    return App(tmp_path)


def run(app, engine, change, backups=None, **kwargs):
    backups = [] if backups is None else backups
    result = core_routes.switch_core(
        app.store, engine, change, data_root=app.data_root,
        backup=lambda kind, root: backups.append((kind, Path(root))), wait=0.05, sleep=lambda _: None, **kwargs)
    return result, backups


def install(app, *versions):
    for version in versions:
        app.store.install(app.bundle(version))


def test_a_stopped_engine_just_gets_the_new_pointer(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store, running=False)

    result, backups = run(app, engine, lambda: app.store.activate("1.1.1"))

    assert result["restarted"] is False and result["running"]["version"] == "1.1.1"
    assert backups == [] and "stop" not in engine.calls
    assert app.store.resolve().version == "1.1.1"


def test_a_running_engine_is_backed_up_then_restarted_on_the_new_core(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store)

    result, backups = run(app, engine, lambda: app.store.activate("1.1.1"))

    assert result == {"running": result["running"], "restarted": True}
    assert backups == [("pre-update", app.data_root)]
    assert engine.calls == ["ensure_idle", "stop", "start:1.1.1"]
    assert engine.core_version == "1.1.1"


def test_a_core_that_will_not_start_is_undone_automatically(app):
    install(app, "1.1.1", "1.1.2")
    app.store.activate("1.1.1")
    engine = FakeEngine(app.store)
    engine.broken.add("1.1.2")

    with pytest.raises(CoreUpdateError, match="已自动恢复到原来的版本"):
        run(app, engine, lambda: app.store.activate("1.1.2"))

    assert app.store.resolve().version == "1.1.1", "pointer must be restored"
    assert engine.running and engine.core_version == "1.1.1", "the previous core must be running again"
    # the failed core is stopped without the idle check, then the old core is started again
    assert engine.calls[-2:] == ["stop(force)", "start:1.1.1"]


def test_a_hung_new_core_times_out_and_is_undone(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store)
    real_start = engine.start

    def start_and_hang():
        real_start()
        engine.hang = app.store.resolve().version == "1.1.1"
    engine.start = start_and_hang

    with pytest.raises(CoreUpdateError, match="已自动恢复"):
        run(app, engine, lambda: app.store.activate("1.1.1"))

    assert app.store.resolve().source == "bundled"
    assert engine.hang is False


def test_an_engine_that_runs_the_wrong_core_is_undone(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store)
    engine.lying["1.1.1"] = "1.1.0"

    with pytest.raises(CoreUpdateError, match="已自动恢复"):
        run(app, engine, lambda: app.store.activate("1.1.1"))

    assert app.store.resolve().source == "bundled"


def test_when_even_the_old_core_fails_the_user_is_told_to_restart_manually(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store)
    engine.broken.update({"1.1.1", "1.1.0"})

    with pytest.raises(CoreUpdateError, match="手动重启引擎"):
        run(app, engine, lambda: app.store.activate("1.1.1"))

    assert app.store.resolve().source == "bundled", "the choice is still restored"


def test_a_busy_engine_blocks_the_switch_before_anything_changes(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store)
    engine.busy = True

    with pytest.raises(EngineError):
        run(app, engine, lambda: app.store.activate("1.1.1"))

    assert app.store.resolve().source == "bundled"
    assert "stop" not in engine.calls


def test_a_failed_backup_aborts_before_the_switch(app):
    install(app, "1.1.1")
    engine = FakeEngine(app.store)

    def broken_backup(kind, root):
        raise OSError("disk full")

    with pytest.raises(OSError):
        core_routes.switch_core(app.store, engine, lambda: app.store.activate("1.1.1"), data_root=app.data_root,
                                backup=broken_backup, wait=0.05, sleep=lambda _: None)

    assert app.store.resolve().source == "bundled" and "stop" not in engine.calls


def test_an_invalid_change_leaves_the_engine_untouched(app):
    engine = FakeEngine(app.store)

    with pytest.raises(CoreUpdateError):
        run(app, engine, lambda: app.store.activate("1.1.1"))   # never installed

    assert "stop" not in engine.calls and engine.running


def test_rollback_restarts_on_the_previous_core(app):
    install(app, "1.1.1", "1.1.2")
    app.store.activate("1.1.1")
    app.store.activate("1.1.2")
    engine = FakeEngine(app.store)

    result, _ = run(app, engine, app.store.rollback)

    assert result["running"]["version"] == "1.1.1" and engine.core_version == "1.1.1"


# ---- the real EngineManager follows the selected core ------------------------------------------

class FakeModels:
    def runtime_selection(self):
        return {"revision": "r" * 64, "model": {"id": "m", "key": "k", "base_url": "https://x.invalid/v1", "model": "n"},
                "zep": {"key": "z"}}


def start_engine(monkeypatch, tmp_path, app):
    root = app.root
    (root / "runtime").mkdir(exist_ok=True)
    (root / "runtime" / "python.exe").write_text("")
    engine = EngineManager(root, FakeModels(), data_root=app.data_root, core=app.store)
    launched = {}

    def popen(command, **kwargs):
        launched.update(command=command, **kwargs)
        return SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr("local_studio.engine.subprocess.Popen", popen)
    monkeypatch.setattr("local_studio.engine.psutil.Process", lambda pid: SimpleNamespace(create_time=lambda: 77.0))
    monkeypatch.setattr(engine, "_port_in_use", lambda: False)
    # Not healthy until the process has been launched, like a real engine.
    monkeypatch.setattr(engine, "status", lambda: {"healthy": "command" in launched,
                                                   "state": "running" if "command" in launched else "stopped"})
    engine.start()
    return engine, launched


def test_the_engine_runs_the_bundled_core_by_default(monkeypatch, tmp_path):
    app = App(tmp_path)
    engine, launched = start_engine(monkeypatch, tmp_path, app)

    assert launched["command"][1] == str(app.root / "backend/run.py")
    assert launched["cwd"] == app.root / "backend"
    assert launched["env"]["MIROFISH_CORE_VERSION"] == "1.1.0"
    assert launched["env"]["MIROFISH_CODE_ROOT"] == str(app.root)


def test_the_engine_runs_an_activated_core_from_the_users_data_directory(monkeypatch, tmp_path):
    app = App(tmp_path)
    app.store.install(app.bundle("1.1.1"))
    app.store.activate("1.1.1")

    engine, launched = start_engine(monkeypatch, tmp_path, app)

    core_dir = app.data_root / "core" / "versions" / "1.1.1"
    assert launched["command"][1] == str(core_dir / "backend/run.py")
    assert launched["cwd"] == core_dir / "backend"
    assert launched["env"]["MIROFISH_CORE_VERSION"] == "1.1.1"
    assert launched["env"]["MIROFISH_CODE_ROOT"] == str(core_dir)
    # The Studio layer still comes from the application, never from the core.
    assert launched["env"]["PYTHONPATH"].split(":")[0] == str(app.root) or str(app.root) in launched["env"]["PYTHONPATH"]
    manifest = json.loads((app.data_root / "studio_data" / "engine.json").read_text())
    assert manifest["script"] == str((core_dir / "backend/run.py").resolve())
    assert manifest["core_version"] == "1.1.1"


def test_a_tampered_core_is_not_started_the_bundled_one_is(monkeypatch, tmp_path):
    app = App(tmp_path)
    app.store.install(app.bundle("1.1.1"))
    app.store.activate("1.1.1")
    (app.data_root / "core/versions/1.1.1/backend/run.py").write_text("import os; os.system('evil')")

    engine, launched = start_engine(monkeypatch, tmp_path, app)

    assert launched["command"][1] == str(app.root / "backend/run.py")
    assert "未通过校验" in engine.core_notice


def test_process_ownership_follows_the_script_that_was_started(monkeypatch, tmp_path):
    app = App(tmp_path)
    app.store.install(app.bundle("1.1.1"))
    app.store.activate("1.1.1")
    first, _ = start_engine(monkeypatch, tmp_path, app)
    core_script = Path(first.script)

    process = SimpleNamespace(create_time=lambda: 77.0,
                              cmdline=lambda: [str(app.root / "runtime/python.exe"), str(core_script)],
                              cwd=lambda: str(core_script.parent))
    monkeypatch.setattr("local_studio.engine.psutil.Process", lambda pid: process)
    again = EngineManager(app.root, FakeModels(), data_root=app.data_root, core=app.store)
    assert again.script == str(core_script)
    assert again._owned_process() is process

    # A process running some other script is not ours, even if the core changed.
    other = SimpleNamespace(create_time=lambda: 77.0,
                            cmdline=lambda: [str(app.root / "runtime/python.exe"), str(app.root / "backend/run.py")],
                            cwd=lambda: str(app.root / "backend"))
    monkeypatch.setattr("local_studio.engine.psutil.Process", lambda pid: other)
    assert again._owned_process() is None
