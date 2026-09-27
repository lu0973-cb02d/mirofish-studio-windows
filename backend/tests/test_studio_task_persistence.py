"""Persistence tests using isolated TaskManager singletons and temporary roots."""

import importlib.util
import json
import sys
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def task_module(monkeypatch, tmp_path):
    # Avoid importing app.__init__ or reading the installation's .env/config.
    prefix = "fixture_persisted_tasks"
    for name in (prefix, prefix + ".models", prefix + ".utils"):
        package = types.ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    locale = types.ModuleType(prefix + ".utils.locale")
    locale.t = lambda key: {"progress.taskComplete": "任务完成", "progress.taskFailed": "任务失败"}.get(key, key)
    monkeypatch.setitem(sys.modules, locale.__name__, locale)
    name = prefix + ".models.task"
    path = Path(__file__).resolve().parents[1] / "app/models/task.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("MIROFISH_STUDIO_ROOT", str(tmp_path))
    spec.loader.exec_module(module)
    return module


def restart(module):
    module.TaskManager._instance = None
    return module.TaskManager()


def task_path(root, task_id):
    return root / "backend/uploads/tasks" / (task_id + ".json")


def test_completed_results_and_original_failure_survive_restart(task_module, tmp_path):
    manager = task_module.TaskManager()
    completed = manager.create_task("graph_build", {"project_id": "project-fixture"})
    manager.complete_task(completed, {"graph_id": "graph-fixture", "node_count": 12, "zep_batch_id": "batch-fixture"})
    failed = manager.create_task("report_generate", {"simulation_id": "simulation-fixture"})
    manager.fail_task(failed, "测试：服务暂时不可用")
    before = {row["task_id"]: row for row in manager.list_tasks()}
    after = restart(task_module)
    assert {row["task_id"]: row for row in after.list_tasks()} == before
    assert after.get_task(completed).status is task_module.TaskStatus.COMPLETED
    assert after.get_task(completed).result["zep_batch_id"] == "batch-fixture"
    assert after.get_task(failed).error == "测试：服务暂时不可用"
    assert len(list((tmp_path / "backend/uploads/tasks").glob("*.json"))) == 2


@pytest.mark.parametrize("processing", [False, True])
def test_interrupted_tasks_are_failed_once_without_claiming_resume(task_module, tmp_path, processing):
    manager = task_module.TaskManager()
    identifier = manager.create_task("simulation_prepare", {"simulation_id": "simulation-fixture"})
    if processing:
        manager.update_task(identifier, status=task_module.TaskStatus.PROCESSING, progress=63,
                            message="准备中", result={"saved_artifact": "fixture-path"})
    recovered = restart(task_module).get_task(identifier)
    assert recovered.status is task_module.TaskStatus.FAILED
    assert "本机引擎曾中断" in recovered.error and "未自动续跑" in recovered.error
    assert "查看已保存的结果后重试" in recovered.message
    assert recovered.progress == (63 if processing else 0)
    if processing:
        assert recovered.result == {"saved_artifact": "fixture-path"}
    persisted = json.loads(task_path(tmp_path, identifier).read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert restart(task_module).get_task(identifier).updated_at == recovered.updated_at


def test_corrupt_task_is_skipped_without_changing_original_or_hiding_good_results(task_module, tmp_path, caplog):
    manager = task_module.TaskManager()
    good = manager.create_task("report_generate")
    manager.complete_task(good, {"report_id": "report-fixture"})
    corrupt = task_path(tmp_path, str(uuid.uuid4()))
    corrupt.write_bytes(b'{"broken":"never-log-this-fixture-secret"')
    wrong_identity = task_path(tmp_path, str(uuid.uuid4()))
    wrong_identity.write_bytes(task_path(tmp_path, good).read_bytes())
    before = [path.read_bytes() for path in (corrupt, wrong_identity)]
    recovered = restart(task_module)
    assert [row["task_id"] for row in recovered.list_tasks()] == [good]
    assert [path.read_bytes() for path in (corrupt, wrong_identity)] == before
    assert "never-log-this" not in caplog.text


def test_extreme_numeric_corruption_cannot_prevent_loading_other_records(task_module, tmp_path):
    manager = task_module.TaskManager()
    good = manager.create_task("graph_build")
    manager.complete_task(good, {"graph_id": "good"})
    corrupted_id = manager.create_task("graph_build")
    path = task_path(tmp_path, corrupted_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["progress"] = 10 ** 500
    path.write_text(json.dumps(raw), encoding="utf-8")
    original = path.read_bytes()
    recovered = restart(task_module)
    assert recovered.get_task(good) is not None
    assert recovered.get_task(corrupted_id) is None
    assert path.read_bytes() == original


def test_nested_credentials_and_provider_errors_are_redacted_before_storage(task_module, tmp_path, monkeypatch):
    secret = "fixture-environment-api-key-never-real"
    monkeypatch.setenv("LLM_API_KEY", secret)
    metadata = {"project_id": "project-fixture", "token_count": 42,
                "provider": {"API-Key": "fixture-metadata-credential", "base": "https://example.invalid/v1"},
                "headers": {"Authorization": "Bearer fixture-header-credential"},
                "nested": [{"password": "fixture-password-credential", "simulation_id": "sim-fixture"}],
                "message": "provider returned fixture-metadata-credential"}
    manager = task_module.TaskManager()
    identifier = manager.create_task("graph_build", metadata)
    manager.update_task(identifier, result={"graph_id": "graph-fixture", "client_secret": "fixture-result-credential"},
                        progress_detail={"safe_count": 2, "credentials": {"key": "fixture-nested-credential"}})
    manager.fail_task(identifier, "Provider failed with " + secret + "; api_key=fixture-labelled-credential")
    public = manager.get_task(identifier).to_dict()
    all_text = task_path(tmp_path, identifier).read_text(encoding="utf-8") + json.dumps(public)
    for value in (secret, "fixture-metadata-credential", "fixture-header-credential", "fixture-password-credential",
                  "fixture-result-credential", "fixture-nested-credential", "fixture-labelled-credential"):
        assert value not in all_text
    assert public["metadata"]["token_count"] == 42
    assert public["result"] == {"graph_id": "graph-fixture"}
    assert metadata["provider"]["API-Key"] == "fixture-metadata-credential"  # caller's input was not modified
    assert restart(task_module).get_task(identifier).error == public["error"]


def test_sensitive_fields_in_a_valid_old_record_are_scrubbed_on_load(task_module, tmp_path):
    manager = task_module.TaskManager()
    identifier = manager.create_task("graph_build")
    manager.complete_task(identifier, {"graph_id": "fixture"})
    path = task_path(tmp_path, identifier)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["metadata"]["secret"] = "fixture-legacy-credential"
    path.write_text(json.dumps(data), encoding="utf-8")
    recovered = restart(task_module)
    assert recovered.get_task(identifier).status is task_module.TaskStatus.COMPLETED
    assert "fixture-legacy-credential" not in path.read_text(encoding="utf-8")


def test_atomic_write_failure_does_not_publish_a_task_or_success_state(task_module, tmp_path, monkeypatch):
    manager = task_module.TaskManager()
    existing = manager.create_task("graph_build")
    path = task_path(tmp_path, existing)
    old_bytes = path.read_bytes()
    before = manager.get_task(existing).to_dict()
    def failure(*args):
        raise PermissionError("fixture-private-storage-error")
    monkeypatch.setattr(task_module.os, "replace", failure)
    with pytest.raises(task_module.TaskPersistenceError) as error:
        manager.complete_task(existing, {"graph_id": "must-not-be-confirmed"})
    assert "fixture-private-storage-error" not in str(error.value)
    assert manager.get_task(existing).to_dict() == before
    assert path.read_bytes() == old_bytes
    with pytest.raises(task_module.TaskPersistenceError):
        manager.create_task("never-created")
    assert len(manager.list_tasks()) == 1
    assert not list(path.parent.glob(".task-*.tmp"))


def test_recovery_write_failure_does_not_publish_half_loaded_singleton(task_module, tmp_path, monkeypatch):
    manager = task_module.TaskManager()
    identifier = manager.create_task("graph_build")
    before = task_path(tmp_path, identifier).read_bytes()
    task_module.TaskManager._instance = None
    with monkeypatch.context() as patch:
        patch.setattr(task_module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("fixture-private-error")))
        with pytest.raises(task_module.TaskPersistenceError):
            task_module.TaskManager()
        assert task_module.TaskManager._instance is None
        assert task_path(tmp_path, identifier).read_bytes() == before
    assert task_module.TaskManager().get_task(identifier).status is task_module.TaskStatus.FAILED


def test_studio_returns_detached_snapshots_so_callers_cannot_bypass_atomic_updates(task_module):
    manager = task_module.TaskManager()
    identifier = manager.create_task("prepare", {"project_id": "original"})
    exposed = manager.get_task(identifier)
    exposed.metadata["project_id"] = "outside-mutation"
    exposed.status = task_module.TaskStatus.COMPLETED
    listing = manager.list_tasks()
    listing[0]["metadata"]["project_id"] = "second-outside-mutation"
    original = manager.get_task(identifier)
    assert original.metadata["project_id"] == "original"
    assert original.status is task_module.TaskStatus.PENDING


def test_invalid_payload_never_overwrites_valid_state(task_module, tmp_path):
    manager = task_module.TaskManager()
    identifier = manager.create_task("prepare")
    before = task_path(tmp_path, identifier).read_bytes()
    with pytest.raises(task_module.TaskPersistenceError):
        manager.update_task(identifier, result={"invalid": object()})
    assert task_path(tmp_path, identifier).read_bytes() == before
    assert manager.get_task(identifier).result is None


def test_write_size_limit_never_accepts_a_record_that_cannot_be_reloaded(task_module, tmp_path):
    manager = task_module.TaskManager()
    identifier = manager.create_task("graph_build")
    original = task_path(tmp_path, identifier).read_bytes()
    with pytest.raises(task_module.TaskPersistenceError, match="过大"):
        manager.complete_task(identifier, {"too_large": "x" * task_module._MAX_TASK_BYTES})
    assert task_path(tmp_path, identifier).read_bytes() == original
    assert manager.get_task(identifier).status is task_module.TaskStatus.PENDING


def test_nonstudio_mode_keeps_existing_in_memory_behavior_and_never_writes_uploads(task_module, tmp_path, monkeypatch):
    monkeypatch.delenv("MIROFISH_STUDIO_ROOT")
    manager = task_module.TaskManager()
    identifier = manager.create_task("legacy", {"legacy_value": object()})
    manager.get_task(identifier).message = "same in-memory object"
    assert manager.get_task(identifier).message == "same in-memory object"
    manager.complete_task(identifier, {"graph_id": "fixture"})
    assert not (tmp_path / "backend").exists()
    assert restart(task_module).get_task(identifier) is None


def test_concurrent_task_updates_are_complete_json_and_survive_restart(task_module, tmp_path):
    manager = task_module.TaskManager()
    def work(number):
        assert task_module.TaskManager() is manager
        identifier = manager.create_task("graph_build", {"index": number})
        manager.update_task(identifier, status=task_module.TaskStatus.PROCESSING, progress=45)
        manager.complete_task(identifier, {"graph_id": f"graph-{number}"})
        return identifier
    with ThreadPoolExecutor(max_workers=6) as pool:
        identifiers = list(pool.map(work, range(18)))
    assert len(set(identifiers)) == 18
    for identifier in identifiers:
        assert json.loads(task_path(tmp_path, identifier).read_text(encoding="utf-8"))["status"] == "completed"
    recovered = restart(task_module)
    assert len(recovered.list_tasks("graph_build")) == 18
    assert all(task["status"] == "completed" for task in recovered.list_tasks())


def test_cleanup_removes_only_expired_terminal_task_files(task_module, tmp_path):
    manager = task_module.TaskManager()
    expired = manager.create_task("old-complete")
    manager.complete_task(expired, {})
    running = manager.create_task("old-active")
    recent = manager.create_task("recent-complete")
    manager.complete_task(recent, {})
    old_date = datetime.now() - timedelta(hours=48)
    for identifier in (expired, running):
        manager._tasks[identifier].created_at = old_date
        manager._write_task(manager._tasks[identifier])
    manager.cleanup_old_tasks(max_age_hours=24)
    assert manager.get_task(expired) is None and not task_path(tmp_path, expired).exists()
    assert manager.get_task(running) is not None and task_path(tmp_path, running).exists()
    assert manager.get_task(recent) is not None and task_path(tmp_path, recent).exists()
