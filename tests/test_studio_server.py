"""Controller/runtime contracts, isolated from real credentials and processes."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import threading
import types
from enum import Enum
from pathlib import Path

import httpx
import pytest

from local_studio import connectivity, server
from local_studio.config_store import ConfigStore
from local_studio.engine import ConfigApplyUncertain, EngineError, EngineManager


HEADERS = {"X-MiroFish-Studio": "1"}
BASE = "http://127.0.0.1:3888"
MODEL_KEY = "isolated-model-fixture-never-real-1234"
ZEP_KEY = "isolated-zep-fixture-never-real-5678"


class FixtureCodec:
    def encrypt(self, value):
        return "fixture:" + base64.b64encode(value.encode()).decode()

    def decrypt(self, value):
        return base64.b64decode(value.split(":", 1)[1]).decode()


class FakeEngine:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.state = {"state": "stopped", "healthy": False, "owned": False, "busy": False}
        self.calls = []
        self.failure = None

    def status(self):
        return dict(self.state)

    def ensure_idle(self):
        self.calls.append("ensure_idle")
        if self.state["busy"]:
            raise EngineError("当前有任务正在执行。")

    def model_snapshot(self):
        self.calls.append("model_snapshot")
        return self.store.runtime_model()

    def apply_config(self):
        self.calls.append("apply_config")
        if self.failure:
            raise self.failure

    def ensure_config_current(self):
        if self.state.get("configuration_synced") is False:
            raise EngineError("配置尚未确认，请先重启引擎。")

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return httpx.Response(202, json={"success": True, "data": {"task_id": "fixture-task"}},
                              headers={"Set-Cookie": "must-not-be-forwarded=1", "Location": "https://elsewhere.invalid"})

    def start(self):
        raise AssertionError("No real or fake engine launch is needed by these tests")

    def stop(self):
        raise AssertionError("No process stopping is permitted by these tests")


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path, codec=FixtureCodec())
    # Response/log redaction must see the same isolated codec and never attempt
    # to decrypt fixture bytes through the real Windows credential store.
    monkeypatch.setattr("local_studio.config_store.ConfigStore", lambda root: store)
    engine = FakeEngine(store)
    app = server.create_app(root=tmp_path, store=store, engine=engine)
    app.config["TESTING"] = True
    # A missed stub must fail visibly instead of making any external request.
    def forbidden(*args, **kwargs):
        raise AssertionError("Real network access is forbidden in controller tests")
    monkeypatch.setattr(connectivity, "_request_json", forbidden)
    return types.SimpleNamespace(root=tmp_path, store=store, engine=engine, app=app,
                                 client=app.test_client())


def call(workbench, path, *, method="GET", body=None, headers=None, base=BASE):
    return workbench.client.open(path, method=method, base_url=base,
                                 headers=HEADERS if headers is None else headers, json=body)


def add_model(workbench, *, name="Fixture model", key=MODEL_KEY):
    return workbench.store.save_model({"name": name, "base_url": "https://example.invalid/v1",
                                      "model": "fixture-chat", "key": key})


@pytest.mark.parametrize(("base", "origin", "headers", "expected"), [
    (BASE, None, HEADERS, 200),
    ("http://localhost:3888", "http://localhost:3888", HEADERS, 200),
    ("http://evil.invalid:3888", None, HEADERS, 403),
    ("http://127.0.0.1:9999", None, HEADERS, 403),
    (BASE, "https://evil.invalid", HEADERS, 403),
    (BASE, "null", HEADERS, 403),
    (BASE, None, {}, 403),
    (BASE, None, {"X-MiroFish-Studio": "true"}, 403),
])
def test_configuration_local_origin_and_custom_header_boundary(workbench, base, origin, headers, expected):
    request_headers = dict(headers)
    if origin is not None:
        request_headers["Origin"] = origin
    response = call(workbench, "/studio-api/config", headers=request_headers, base=base)
    assert response.status_code == expected
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Access-Control-Allow-Origin" not in response.headers


def test_engine_write_routes_also_require_workbench_header(workbench):
    workbench.engine.state.update(healthy=True, owned=True, state="running")
    response = call(workbench, "/api/simulation/start", method="POST", body={}, headers={})
    assert response.status_code == 403
    assert workbench.engine.calls == []


def test_save_and_read_public_configuration_never_return_key_or_ciphertext(workbench):
    response = call(workbench, "/studio-api/models", method="POST", body={
        "name": "Fixture", "base_url": "https://example.invalid/v1", "model": "fixture-chat", "key": MODEL_KEY})
    assert response.status_code == 200
    model = response.json["data"]
    call(workbench, "/studio-api/zep", method="POST", body={"name": "Fixture Zep", "key": ZEP_KEY})
    public = call(workbench, "/studio-api/config")
    combined = response.get_data(as_text=True) + public.get_data(as_text=True)
    assert MODEL_KEY not in combined and ZEP_KEY not in combined and "key_enc" not in combined
    assert "fixture:" not in combined and model["has_key"]
    assert workbench.store.runtime_model(model["id"])["key"] == MODEL_KEY


def test_discovery_uses_saved_key_but_draft_values_are_not_persisted(workbench, monkeypatch):
    saved = add_model(workbench)
    captured = []
    def discover(profile):
        captured.append(profile)
        return {"ok": True, "models": ["draft-model"], "message": "fixture", "latency_ms": 1}
    monkeypatch.setattr(connectivity, "discover_models", discover)
    response = call(workbench, "/studio-api/models/discover", method="POST", body={
        "id": saved["id"], "base_url": "http://localhost:11434/v1", "model": "draft-model", "key": ""})
    assert response.status_code == 200
    assert captured[0]["key"] == MODEL_KEY
    assert captured[0]["base_url"] == "http://localhost:11434/v1"
    assert MODEL_KEY not in response.get_data(as_text=True)
    persisted = workbench.store.runtime_model(saved["id"])
    assert persisted["base_url"] == "https://example.invalid/v1"
    assert persisted["model"] == "fixture-chat"


def test_busy_engine_allows_saving_an_inactive_preset_but_blocks_activation(workbench):
    workbench.engine.state.update(healthy=True, owned=True, busy=True, state="running")
    saved = call(workbench, "/studio-api/models", method="POST", body={
        "name": "Later", "base_url": "https://later.invalid/v1", "model": "later-chat", "key": MODEL_KEY})
    assert saved.status_code == 200
    response = call(workbench, f"/studio-api/models/{saved.json['data']['id']}/activate", method="POST", body={})
    assert response.status_code == 409
    assert workbench.store.public()["active_model_id"] == ""
    assert "apply_config" not in workbench.engine.calls


@pytest.mark.parametrize("kind", ["models", "zep"])
def test_busy_engine_blocks_edits_to_a_live_connection(workbench, kind):
    if kind == "models":
        item = add_model(workbench)
        workbench.store.activate_model(item["id"])
    else:
        item = workbench.store.save_zep({"name": "Zep", "key": ZEP_KEY, "group": "fixture-group"})
        workbench.store.activate_zep(item["id"])
    before = workbench.store.public()
    workbench.engine.state.update(healthy=True, owned=True, busy=True, state="running")
    response = call(workbench, f"/studio-api/{kind}", method="POST", body={
        "id": item["id"], "name": "must-not-change", "key": "different-fixture-key"})
    assert response.status_code == 409
    assert workbench.store.public() == before
    assert "apply_config" not in workbench.engine.calls


@pytest.mark.parametrize("kind", ["models", "zep"])
def test_failed_live_profile_edit_restores_fields_and_secret(workbench, kind):
    if kind == "models":
        item = add_model(workbench)
        workbench.store.activate_model(item["id"])
        runtime = workbench.store.runtime_model
    else:
        item = workbench.store.save_zep({"name": "Zep", "key": ZEP_KEY, "group": "fixture-group"})
        workbench.store.activate_zep(item["id"])
        runtime = workbench.store.runtime_zep
    before = runtime()
    workbench.engine.state.update(healthy=True, owned=True, state="running")
    workbench.engine.failure = EngineError("fixture-safe-apply-failure")
    response = call(workbench, f"/studio-api/{kind}", method="POST", body={
        "id": item["id"], "name": "must-roll-back", "key": "different-fixture-key"})
    assert response.status_code == 409
    assert runtime() == before
    assert MODEL_KEY not in response.get_data(as_text=True) and ZEP_KEY not in response.get_data(as_text=True)


def test_successful_activation_applies_once_without_restarting_engine(workbench):
    item = add_model(workbench)
    workbench.engine.state.update(healthy=True, owned=True, state="running")
    response = call(workbench, f"/studio-api/models/{item['id']}/activate", method="POST", body={})
    assert response.status_code == 200
    assert workbench.store.public()["active_model_id"] == item["id"]
    assert workbench.engine.calls == ["ensure_idle", "model_snapshot", "apply_config"]
    assert MODEL_KEY not in response.get_data(as_text=True)


@pytest.mark.parametrize("kind", ["models", "zep"])
@pytest.mark.parametrize("has_previous", [False, True])
def test_failed_activation_rolls_back_even_the_first_selection(workbench, kind, has_previous):
    active_field = "active_model_id" if kind == "models" else "active_zep_id"
    if kind == "models":
        save = lambda name: add_model(workbench, name=name)
        activate = workbench.store.activate_model
    else:
        save = lambda name: workbench.store.save_zep({"name": name, "key": ZEP_KEY})
        activate = workbench.store.activate_zep
    previous = save("previous") if has_previous else None
    if previous:
        activate(previous["id"])
    chosen = save("chosen")
    workbench.engine.failure = EngineError("配置应用失败（测试故障）")
    response = call(workbench, f"/studio-api/{kind}/{chosen['id']}/activate", method="POST", body={})
    assert response.status_code == 409
    assert workbench.store.public()[active_field] == (previous["id"] if previous else "")


def test_active_profile_deletion_is_blocked_while_engine_is_running(workbench):
    model = add_model(workbench)
    zep = workbench.store.save_zep({"name": "Zep", "key": ZEP_KEY})
    workbench.store.activate_model(model["id"])
    workbench.engine.state.update(healthy=True, owned=True, state="running")
    assert call(workbench, f"/studio-api/models/{model['id']}", method="DELETE").status_code == 409
    assert call(workbench, f"/studio-api/zep/{zep['id']}", method="DELETE").status_code == 409
    assert len(workbench.store.public()["models"]) == len(workbench.store.public()["zep"]) == 1


def test_unexpected_exception_is_sanitized(workbench, monkeypatch):
    saved = add_model(workbench)
    def failure(*args):
        raise RuntimeError("never-display-" + MODEL_KEY)
    monkeypatch.setattr(workbench.engine, "model_snapshot", failure)
    response = call(workbench, f"/studio-api/models/{saved['id']}/activate", method="POST", body={})
    assert response.status_code == 500
    assert MODEL_KEY not in response.get_data(as_text=True)
    assert "never-display" not in response.get_data(as_text=True)


def test_configuration_size_limit_rejects_before_saving(workbench):
    response = call(workbench, "/studio-api/models", method="POST", body={"name": "x" * (1024 * 1024)})
    assert response.status_code == 413
    assert workbench.store.public()["models"] == []


def write_json(root, relative, payload):
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload), encoding="utf-8")


def test_records_route_links_latest_simulation_and_report_without_payload_contents(workbench):
    write_json(workbench.root, "backend/uploads/projects/p1/project.json", {
        "project_id": "p1", "name": "Fixture project", "status": "ready", "created_at": "2026-01-01",
        "secret_source_contents": "fixture-private-source"})
    for sim, date in (("s1", "2026-01-01"), ("s2", "2026-01-02")):
        write_json(workbench.root, f"backend/uploads/simulations/{sim}/state.json", {
            "simulation_id": sim, "project_id": "p1", "status": "prepared", "created_at": date})
    write_json(workbench.root, "backend/uploads/simulations/s2/run_state.json", {
        "runner_status": "completed", "current_round": 40, "total_rounds": 40})
    write_json(workbench.root, "backend/uploads/reports/r1/meta.json", {
        "report_id": "r1", "simulation_id": "s2", "status": "completed", "created_at": "2026-01-03"})
    response = call(workbench, "/studio-api/records")
    assert response.status_code == 200
    result = response.json["data"]
    assert result["projects"][0]["simulation_id"] == "s2"
    assert result["projects"][0]["report_id"] == "r1"
    assert result["projects"][0]["simulation_status"] == "completed"
    assert "fixture-private-source" not in response.get_data(as_text=True)


def test_restore_rejects_traversal_and_running_engine_before_touching_backups(workbench, monkeypatch):
    events = []
    fake = types.SimpleNamespace(verify_backup=lambda path, **kwargs: events.append("verify"),
                                 create_backup=lambda *args, **kwargs: events.append("create"),
                                 restore_backup=lambda path, **kwargs: events.append("restore"))
    monkeypatch.setitem(sys.modules, "record_backup", fake)
    response = call(workbench, "/studio-api/backups/restore", method="POST", body={"name": "../records-secret.zip"})
    assert response.status_code == 400 and events == []
    workbench.engine.state.update(owned=True, healthy=False)
    response = call(workbench, "/studio-api/backups/restore", method="POST", body={"name": "records-fixture.zip"})
    assert response.status_code == 409 and events == []


def test_restore_verifies_then_preserves_previous_records_before_restore(workbench, monkeypatch):
    folder = workbench.root / "record_backups"
    folder.mkdir()
    selected = folder / "records-fixture.zip"
    selected.write_bytes(b"not-a-real-archive")
    events = []
    def verify(path, **kwargs):
        assert path == selected
        assert kwargs.get("root", workbench.root) == workbench.root
        events.append("verify")
        return {"file_count": 2}
    def create(label, **kwargs):
        assert label == "pre-restore"
        assert kwargs.get("root", workbench.root) == workbench.root
        events.append("snapshot")
        return folder / "records-pre-restore.zip"
    def restore(path, **kwargs):
        assert path == selected
        assert kwargs.get("root", workbench.root) == workbench.root
        events.append("restore")
        return {"file_count": 2}, None
    monkeypatch.setitem(sys.modules, "record_backup", types.SimpleNamespace(
        verify_backup=verify, create_backup=create, restore_backup=restore))
    response = call(workbench, "/studio-api/backups/restore", method="POST", body={"name": selected.name})
    assert response.status_code == 200
    assert events == ["verify", "snapshot", "restore"]
    assert response.json["data"]["previous_backup"] == "records-pre-restore.zip"


def test_operational_logs_cannot_echo_saved_credentials(workbench):
    add_model(workbench)
    workbench.store.save_zep({"name": "Zep", "key": ZEP_KEY})
    log = workbench.root / "studio_data/engine.log"
    log.write_text('MiroFish Backend started\nMiroFish Backend key=' + MODEL_KEY +
                   '\n127.0.0.1 - "GET /api/status?token=' + ZEP_KEY + ' HTTP/1.1" 200 -\n', encoding="utf-8")
    response = call(workbench, "/studio-api/logs")
    assert response.status_code == 200
    assert MODEL_KEY not in response.get_data(as_text=True)
    assert ZEP_KEY not in response.get_data(as_text=True)


def test_static_assets_spa_routes_and_traversal_do_not_expose_files(workbench):
    dist = workbench.root / "frontend/dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Fixture SPA</html>", encoding="utf-8")
    (dist / "assets/app.js").write_text("window.fixture = true;", encoding="utf-8")
    (workbench.root / "private.env").write_text("PRIVATE_FIXTURE_NOT_FOR_BROWSER", encoding="utf-8")
    assert call(workbench, "/simulation/fixture/start", headers={}).get_data(as_text=True) == "<html>Fixture SPA</html>"
    asset = call(workbench, "/assets/app.js", headers={})
    assert asset.status_code == 200 and "javascript" in asset.content_type
    assert "PRIVATE_FIXTURE" not in call(workbench, "/../../private.env", headers={}).get_data(as_text=True)
    assert call(workbench, "/studio-api/missing").status_code == 404


def test_proxy_preserves_submission_but_drops_untrusted_auth_and_upstream_cookies(workbench):
    workbench.engine.state.update(healthy=True, owned=True, state="running")
    response = call(workbench, "/api/simulation/start?mode=a&mode=b", method="POST", body={"simulation_id": "fixture"},
                    headers={**HEADERS, "Authorization": "Bearer never-forward", "X-MiroFish-Engine-Token": "never-forward"})
    assert response.status_code == 202
    method, path, options = workbench.engine.calls[-1]
    assert method == "POST" and path == "/api/simulation/start"
    assert options["params"] == [("mode", "a"), ("mode", "b")]
    assert not any(key.lower() in {"authorization", "x-mirofish-engine-token"} for key in options["headers"])
    assert "Set-Cookie" not in response.headers and "Location" not in response.headers


def test_unknown_engine_cannot_restore_records(workbench):
    workbench.engine.state.update(state="error", healthy=False, owned=False)
    response = call(workbench, "/studio-api/backups/restore", method="POST", body={"name": "records-fixture.zip"})
    assert response.status_code == 409
    assert not (workbench.root / "record_backups").exists()


def test_uncertain_apply_retains_selected_configuration(workbench):
    old = add_model(workbench, name="Old")
    chosen = add_model(workbench, name="Chosen")
    workbench.store.activate_model(old["id"])
    workbench.engine.state.update(state="running", healthy=True, owned=True)
    workbench.engine.failure = ConfigApplyUncertain("配置应用结果待确认。")
    response = call(workbench, f"/studio-api/models/{chosen['id']}/activate", method="POST", body={})
    assert response.status_code == 409
    assert workbench.store.public()["active_model_id"] == chosen["id"]


def test_unconfirmed_configuration_cannot_submit_new_work(workbench):
    workbench.engine.state.update(state="running", healthy=True, owned=True, configuration_synced=False)
    response = call(workbench, "/api/simulation/start", method="POST", body={"simulation_id": "fixture"})
    assert response.status_code == 409
    assert not any(isinstance(item, tuple) for item in workbench.engine.calls)


def test_upstream_error_redacts_saved_keys_and_drops_traceback(workbench, monkeypatch):
    add_model(workbench)
    workbench.engine.state.update(state="running", healthy=True, owned=True)
    monkeypatch.setattr(workbench.engine, "request", lambda *args, **kwargs: httpx.Response(500, json={
        "success": False, "error": "Provider rejected " + MODEL_KEY,
        "traceback": "private stack " + MODEL_KEY, "message": "Please retry later."}))
    response = call(workbench, "/api/simulation/start", method="POST", body={})
    assert response.status_code == 500
    assert MODEL_KEY not in response.get_data(as_text=True)
    assert "traceback" not in response.json
    assert response.json["message"] == "Please retry later."


def test_quit_cannot_shutdown_when_engine_refuses_stop(workbench, monkeypatch):
    finished = threading.Event()
    workbench.app.config["STUDIO_SHUTDOWN"] = finished.set
    def refuse():
        raise EngineError("任务仍在执行。")
    monkeypatch.setattr(workbench.engine, "stop", refuse)
    assert call(workbench, "/studio-api/quit", method="POST", body={}).status_code == 409
    assert not finished.is_set()


def test_quit_shuts_down_only_after_engine_stop(workbench, monkeypatch):
    events = []
    finished = threading.Event()
    monkeypatch.setattr(workbench.engine, "stop", lambda: events.append("engine-stopped"))
    def shutdown():
        events.append("workbench-stopped")
        finished.set()
    workbench.app.config["STUDIO_SHUTDOWN"] = shutdown
    assert call(workbench, "/studio-api/quit", method="POST", body={}).status_code == 200
    assert finished.wait(2)
    assert events == ["engine-stopped", "workbench-stopped"]


def test_engine_model_snapshot_only_permits_missing_key_for_loopback(workbench):
    engine = EngineManager(workbench.root, workbench.store)
    cloud = add_model(workbench, key="")
    workbench.store.activate_model(cloud["id"])
    with pytest.raises(EngineError, match="API Key"):
        engine.model_snapshot()
    local = workbench.store.save_model({"name": "Local", "base_url": "http://localhost:11434/v1", "model": "local"})
    workbench.store.activate_model(local["id"])
    assert engine.model_snapshot()["key"] == "local-no-key"
    assert workbench.store.runtime_model()["key"] == ""


def test_engine_apply_error_never_propagates_upstream_error_body(workbench, monkeypatch):
    engine = EngineManager(workbench.root, workbench.store)
    monkeypatch.setattr(engine, "status", lambda: {"healthy": True})
    monkeypatch.setattr(engine, "request", lambda *args, **kwargs: httpx.Response(
        500, json={"success": False, "error": "upstream accidentally echoed " + MODEL_KEY}))
    with pytest.raises(EngineError) as error:
        engine.apply_config()
    assert MODEL_KEY not in str(error.value)
    assert "upstream accidentally" not in str(error.value)


def test_engine_requests_are_loopback_only_without_proxy_redirect_or_caller_token(workbench, monkeypatch):
    engine = EngineManager(workbench.root, workbench.store)
    engine.token = "fixture-owned-engine-token"
    captured = []
    real_client = httpx.Client
    def handler(request):
        captured.append(request)
        return httpx.Response(302, headers={"Location": "https://outside.invalid"})
    def client_factory(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(httpx, "Client", client_factory)
    response = engine.request("GET", "/health", headers={"X-MiroFish-Engine-Token": "untrusted"})
    assert response.status_code == 302 and len(captured) == 1
    assert str(captured[0].url) == "http://127.0.0.1:5001/health"
    assert captured[0].headers["X-MiroFish-Engine-Token"] == "fixture-owned-engine-token"


@pytest.fixture
def runtime_module(monkeypatch):
    """Load the real runtime file against fake app dependencies, never app.__init__."""
    prefix = "fixture_studio_runtime_package"
    modules = {name: types.ModuleType(name) for name in (
        prefix, prefix + ".config", prefix + ".models", prefix + ".models.task",
        prefix + ".services", prefix + ".services.simulation_runner")}
    modules[prefix].__path__ = []
    fake_config = types.SimpleNamespace(LLM_API_KEY="old-fixture", LLM_BASE_URL="https://old.invalid/v1",
                                        LLM_MODEL_NAME="old", ZEP_API_KEY="old-zep-fixture")
    tasks = []
    class Status(str, Enum):
        RUNNING = "running"
        STARTING = "starting"
        PAUSED = "paused"
        STOPPING = "stopping"
        COMPLETED = "completed"
        FAILED = "failed"
    runner = types.SimpleNamespace(_run_states={}, _processes={})
    modules[prefix + ".config"].Config = fake_config
    modules[prefix + ".models.task"].TaskManager = lambda: types.SimpleNamespace(list_tasks=lambda: tasks)
    modules[prefix + ".services.simulation_runner"].SimulationRunner = runner
    modules[prefix + ".services.simulation_runner"].RunnerStatus = Status
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[1] / "backend/app/studio_runtime.py"
    spec = importlib.util.spec_from_file_location(prefix + ".studio_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.os = types.SimpleNamespace(environ={"MIROFISH_STUDIO_ROOT": "fixture-root"})
    return types.SimpleNamespace(module=module, config=fake_config, tasks=tasks, runner=runner, Status=Status)


def test_completed_live_interviews_do_not_keep_workflow_busy(runtime_module):
    runtime = runtime_module
    process = types.SimpleNamespace(poll=lambda: None)
    runtime.runner._run_states["finished"] = types.SimpleNamespace(runner_status=runtime.Status.COMPLETED)
    runtime.runner._processes["finished"] = process
    result = runtime.module.health_snapshot()
    assert result["busy"] is False
    assert result["interview_ids"] == ["finished"] and result["interview_count"] == 1
    runtime.runner._run_states["active"] = types.SimpleNamespace(runner_status=runtime.Status.RUNNING)
    assert runtime.module.health_snapshot()["busy"] is True


def test_runtime_busy_guard_precedes_configuration_reads(runtime_module, monkeypatch):
    runtime = runtime_module
    runtime.tasks.append({"status": "processing"})
    def forbidden(*args):
        raise AssertionError("Busy runtime must not read or apply any credentials")
    import local_studio.config_store as config_module
    monkeypatch.setattr(config_module, "ConfigStore", forbidden)
    with pytest.raises(ValueError, match="任务"):
        runtime.module.apply_selected_config()
    assert runtime.config.LLM_API_KEY == "old-fixture"
    assert "LLM_API_KEY" not in runtime.module.os.environ


def test_runtime_applies_selected_snapshot_without_exposing_keys_or_closing_interviews(workbench, runtime_module, monkeypatch):
    model = add_model(workbench)
    zep = workbench.store.save_zep({"name": "Zep", "key": ZEP_KEY})
    workbench.store.activate_model(model["id"])
    workbench.store.activate_zep(zep["id"])
    runtime = runtime_module
    interview = types.SimpleNamespace(poll=lambda: None)
    runtime.runner._run_states["finished"] = types.SimpleNamespace(runner_status=runtime.Status.COMPLETED)
    runtime.runner._processes["finished"] = interview
    import local_studio.config_store as config_module
    monkeypatch.setattr(config_module, "ConfigStore", lambda *args: workbench.store)
    result = runtime.module.apply_selected_config()
    assert result["model_id"] == model["id"]
    assert MODEL_KEY not in str(result) and ZEP_KEY not in str(result)
    assert runtime.config.LLM_API_KEY == MODEL_KEY and runtime.config.ZEP_API_KEY == ZEP_KEY
    assert runtime.module.os.environ["MIROFISH_MODEL_ID"] == model["id"]
    assert runtime.runner._processes["finished"] is interview
