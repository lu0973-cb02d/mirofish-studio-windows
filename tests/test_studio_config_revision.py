"""Lost-response, revision and backend-response boundaries without real services."""

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

import httpx
import pytest
from flask import Blueprint, jsonify

from local_studio.config_store import ConfigError, ConfigStore
from local_studio.engine import ConfigApplyUncertain, EngineError, EngineManager


class FixtureCodec:
    def encrypt(self, value):
        return "fixture:" + base64.b64encode(value.encode()).decode()

    def decrypt(self, value):
        return base64.b64decode(value.split(":", 1)[1]).decode()


@pytest.fixture
def selected(tmp_path):
    store = ConfigStore(tmp_path, codec=FixtureCodec())
    model = store.save_model({"name": "Fixture model", "base_url": "https://example.invalid/v1",
                              "model": "old-model", "key": "revision-model-fixture-key"})
    zep = store.save_zep({"name": "Fixture Zep", "key": "revision-zep-fixture-key", "group": "fixture"})
    store.activate_model(model["id"])
    store.activate_zep(zep["id"])
    return types.SimpleNamespace(root=tmp_path, store=store, model=model, zep=zep)


def test_revision_never_decrypts_and_ignores_unselected_or_display_only_changes(selected, monkeypatch):
    store = selected.store
    original = store.runtime_revision()
    assert len(original) == 64 and all(character in "0123456789abcdef" for character in original)
    store.save_model({"name": "Unselected", "base_url": "https://other.invalid/v1", "model": "other"})
    store.save_model({"id": selected.model["id"], "name": "Renamed only"})
    store.set_auto_zep(False)
    monkeypatch.setattr(store.codec, "decrypt", lambda *_: (_ for _ in ()).throw(AssertionError("must not decrypt")))
    assert store.runtime_revision() == original
    assert "key_enc" not in json.dumps(store.public())


@pytest.mark.parametrize(("kind", "change"), [
    ("model", {"base_url": "https://changed.invalid/v1"}),
    ("model", {"model": "different-model"}),
    ("model", {"key": "different-fixture-model-key"}),
    ("zep", {"key": "different-fixture-zep-key"}),
    ("zep", {"group": "different-group"}),
])
def test_revision_covers_selected_runtime_inputs(selected, kind, change):
    original = selected.store.runtime_revision()
    if kind == "model":
        selected.store.save_model({"id": selected.model["id"], **change})
    else:
        selected.store.save_zep({"id": selected.zep["id"], **change})
    assert selected.store.runtime_revision() != original


def test_selection_rejects_stale_revision_before_decrypting(selected, monkeypatch):
    stale = selected.store.runtime_revision()
    selected.store.save_model({"id": selected.model["id"], "model": "new-model"})
    monkeypatch.setattr(selected.store.codec, "decrypt", lambda *_: (_ for _ in ()).throw(AssertionError("must not decrypt")))
    with pytest.raises(ConfigError, match="已变化"):
        selected.store.runtime_selection(expected_revision=stale)


@pytest.fixture
def engine_case(selected, monkeypatch):
    engine = EngineManager(selected.root, selected.store)
    engine.instance = "fixture-instance"
    engine.pid = 1234
    old_revision = selected.store.runtime_revision()
    selected.store.save_model({"id": selected.model["id"], "model": "new-model"})
    target = selected.store.runtime_revision()
    health = {"service": "MiroFish Backend", "studio_instance": engine.instance,
              "runtime_revision": old_revision, "busy": False}
    monkeypatch.setattr(engine, "_owned_process", lambda: object())
    monkeypatch.setattr(engine, "_port_in_use", lambda: False)
    monkeypatch.setattr(engine, "health", lambda: health)
    return types.SimpleNamespace(engine=engine, selected=selected, old=old_revision, target=target, health=health)


def test_lost_apply_reply_is_success_when_health_confirms_committed_revision(engine_case, monkeypatch):
    case = engine_case
    def request(method, path, **kwargs):
        assert method == "POST" and path == "/api/studio/apply-config"
        assert kwargs["json"] == {"expected_revision": case.target}
        case.health["runtime_revision"] = case.target
        raise httpx.ReadTimeout("fixture-secret-in-transport-error")
    monkeypatch.setattr(case.engine, "request", request)
    result = case.engine.apply_config()
    assert result["confirmed_by_health"] is True
    assert case.engine.status()["configuration_synced"] is True
    assert case.engine.ensure_config_current()["healthy"] is True
    assert "fixture-secret" not in str(result)


@pytest.mark.parametrize("confirmation", ["old", "missing", "foreign"])
def test_unknown_apply_outcome_never_claims_failure_or_sync(engine_case, monkeypatch, confirmation):
    case = engine_case
    monkeypatch.setattr(case.engine, "status", lambda: {"healthy": True, "owned": True, "state": "running"})
    monkeypatch.setattr(case.engine, "request", lambda *args, **kwargs: (_ for _ in ()).throw(
        httpx.ReadTimeout("transport echoed revision-model-fixture-key")))
    health = None if confirmation == "missing" else dict(case.health)
    if confirmation == "foreign":
        health.update(studio_instance="some-other-engine", runtime_revision=case.target)
    monkeypatch.setattr(case.engine, "health", lambda: health)
    with pytest.raises(ConfigApplyUncertain) as error:
        case.engine.apply_config()
    assert "revision-model-fixture-key" not in str(error.value)
    assert case.selected.store.runtime_revision() == case.target


def test_explicit_not_applied_response_is_a_definite_failure(engine_case, monkeypatch):
    case = engine_case
    monkeypatch.setattr(case.engine, "request", lambda *args, **kwargs: httpx.Response(409, json={
        "success": False, "applied": False, "code": "CONFIG_NOT_APPLIED", "expected_revision": case.target,
        "error": "provider body must never be echoed revision-model-fixture-key"}))
    with pytest.raises(EngineError) as error:
        case.engine.apply_config()
    assert not isinstance(error.value, ConfigApplyUncertain)
    assert "provider body" not in str(error.value) and "revision-model-fixture-key" not in str(error.value)


@pytest.mark.parametrize("reply", [
    httpx.Response(200, json=None),
    httpx.Response(200, json=["wrong schema"]),
    httpx.Response(200, text="not JSON"),
    httpx.Response(200, json={"success": True, "data": {"runtime_revision": "old"}}),
    httpx.Response(500, json={"success": False, "error": "fixture-private-provider-error"}),
])
def test_malformed_or_unrecognized_reply_cannot_trigger_rollback(engine_case, monkeypatch, reply):
    monkeypatch.setattr(engine_case.engine, "request", lambda *args, **kwargs: reply)
    with pytest.raises(ConfigApplyUncertain) as error:
        engine_case.engine.apply_config()
    assert "fixture-private-provider-error" not in str(error.value)


def test_unsynced_engine_blocks_new_work_but_remains_stoppable(engine_case, monkeypatch):
    case = engine_case
    state = case.engine.status()
    assert state["state"] == "running" and state["healthy"] and not state["configuration_synced"]
    with pytest.raises(ConfigApplyUncertain):
        case.engine.ensure_config_current()
    case.engine.ensure_idle()  # Revision mismatch must not prohibit stop/restart.
    terminated = []
    process = types.SimpleNamespace(children=lambda recursive: [], terminate=lambda: terminated.append(True))
    monkeypatch.setattr(case.engine, "_owned_process", lambda: process if case.engine.pid else None)
    monkeypatch.setattr(case.engine, "health", lambda: case.health if case.engine.pid else None)
    monkeypatch.setattr("local_studio.engine.psutil.wait_procs", lambda *args, **kwargs: ([], []))
    assert case.engine.stop()["state"] == "stopped"
    assert terminated == [True]


def test_unknown_program_on_port_is_not_reported_as_stopped(selected, monkeypatch):
    engine = EngineManager(selected.root, selected.store)
    monkeypatch.setattr(engine, "health", lambda: None)
    monkeypatch.setattr(engine, "_owned_process", lambda: None)
    called = []
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): assert 0 < timeout <= 0.3
        def connect_ex(self, address): called.append(address); return 0
    monkeypatch.setattr("local_studio.engine.socket.socket", Probe)
    state = engine.status()
    assert state["state"] == "error" and not state["healthy"] and not state["owned"]
    assert called == [("127.0.0.1", 5001)]


@pytest.fixture
def backend_case(selected, monkeypatch):
    """Load actual factory/runtime files with fake app deps and a fake environment."""
    prefix = "fixture_revision_backend"
    root = Path(__file__).resolve().parents[1]
    logger = types.SimpleNamespace(info=lambda *args: None, debug=lambda *args: None)
    config = type("FixtureConfig", (), {"DEBUG": False, "LLM_API_KEY": "old-fixture-key",
                                        "LLM_BASE_URL": "https://old.invalid/v1", "LLM_MODEL_NAME": "old-model",
                                        "ZEP_API_KEY": "old-zep-fixture"})
    tasks = []
    runner = types.SimpleNamespace(register_cleanup=lambda: None, _run_states={}, _processes={})
    for name in ("utils", "services", "models"):
        module = types.ModuleType(prefix + "." + name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, module.__name__, module)
    children = {
        "config": {"Config": config},
        "utils.logger": {"setup_logger": lambda *_: logger, "get_logger": lambda *_: logger},
        "models.task": {"TaskManager": lambda: types.SimpleNamespace(list_tasks=lambda: tasks)},
        "services.simulation_runner": {"SimulationRunner": runner, "RunnerStatus": types.SimpleNamespace()},
        "api": {name: Blueprint(name, prefix) for name in ("graph_bp", "simulation_bp", "report_bp")},
    }
    for suffix, values in children.items():
        module = types.ModuleType(prefix + "." + suffix)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    def load(name, source, package=False):
        spec = importlib.util.spec_from_file_location(name, root / source,
                    submodule_search_locations=[str(root / "backend/app")] if package else None)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module
    factory = load(prefix, "backend/app/__init__.py", package=True)
    runtime = load(prefix + ".studio_runtime", "backend/app/studio_runtime.py")
    environ = {"MIROFISH_STUDIO_ROOT": str(selected.root), "MIROFISH_ENGINE_TOKEN": "fixture-engine-token",
               "MIROFISH_ENGINE_INSTANCE": "fixture-instance", "MIROFISH_CONFIG_REVISION": "old-revision",
               "MIROFISH_MODEL_ID": "old-id"}
    factory.os = runtime.os = types.SimpleNamespace(environ=environ)
    monkeypatch.setattr("local_studio.config_store.ConfigStore", lambda *_: selected.store)
    redactions = []
    def identity_redaction(value, **kwargs):
        redactions.append(kwargs)
        return value
    monkeypatch.setattr("local_studio.redaction.redact_payload", identity_redaction)
    app = factory.create_app(config)
    return types.SimpleNamespace(factory=factory, runtime=runtime, config=config, environ=environ,
                                 tasks=tasks, selected=selected, app=app, redactions=redactions)


def test_backend_applies_only_matching_atomic_selection_and_reports_revision(backend_case):
    case = backend_case
    revision = case.selected.store.runtime_revision()
    result = case.runtime.apply_selected_config(expected_revision=revision)
    assert result["runtime_revision"] == revision
    assert case.runtime.health_snapshot()["runtime_revision"] == revision
    assert case.config.LLM_MODEL_NAME == "old-model"
    assert "revision-model-fixture-key" not in str(result)
    case.selected.store.save_model({"id": case.selected.model["id"], "model": "changed-after-request"})
    with pytest.raises(ConfigError):
        case.runtime.apply_selected_config(expected_revision=revision)
    assert case.config.LLM_MODEL_NAME == "old-model"
    assert case.runtime.health_snapshot()["runtime_revision"] == revision


def test_backend_busy_rejection_cannot_change_runtime_revision(backend_case):
    case = backend_case
    case.tasks.append({"status": "processing"})
    with pytest.raises(ValueError, match="任务"):
        case.runtime.apply_selected_config(expected_revision=case.selected.store.runtime_revision())
    assert case.environ["MIROFISH_CONFIG_REVISION"] == "old-revision"
    assert case.config.LLM_API_KEY == "old-fixture-key"


def test_backend_apply_route_requires_revision_and_marks_known_rejections(backend_case):
    case = backend_case
    client = case.app.test_client()
    headers = {"X-MiroFish-Engine-Token": "fixture-engine-token"}
    missing = client.post("/api/studio/apply-config", json={}, headers=headers)
    assert missing.status_code == 409 and missing.json["code"] == "CONFIG_NOT_APPLIED"
    stale = client.post("/api/studio/apply-config", json={"expected_revision": "0" * 64}, headers=headers)
    assert stale.status_code == 409 and stale.json["applied"] is False
    assert stale.json["expected_revision"] == "0" * 64
    revision = case.selected.store.runtime_revision()
    applied = client.post("/api/studio/apply-config", json={"expected_revision": revision}, headers=headers)
    assert applied.status_code == 200 and applied.json["data"]["runtime_revision"] == revision
    assert client.get("/health").json["runtime_revision"] == revision


def test_backend_json_redaction_rewrites_body_and_content_length(backend_case, monkeypatch):
    case = backend_case
    @case.app.get("/fixture-error")
    def error():
        return jsonify(error="fixture-credential-should-not-escape", traceback="private fixture traceback"), 500
    calls = []
    def redact(value, **kwargs):
        calls.append((value, kwargs))
        return {"error": "[hidden]"}
    monkeypatch.setattr("local_studio.redaction.redact_payload", redact)
    response = case.app.test_client().get("/fixture-error")
    assert response.status_code == 500 and response.json == {"error": "[hidden]"}
    assert response.content_length == len(response.data)
    assert b"fixture-credential" not in response.data
    assert calls[0][1] == {"root": str(case.selected.root), "strip_traceback": True,
                           "strip_sensitive_fields": True}


@pytest.mark.parametrize("payload,expected", [({"success": True, "data": {"key": "name", "tokens": 12}}, False),
                                               ({"success": False, "error": "failed"}, True)])
def test_backend_redaction_mode_preserves_normal_business_fields(backend_case, payload, expected):
    case = backend_case
    @case.app.get("/fixture-payload")
    def body():
        return jsonify(payload)
    response = case.app.test_client().get("/fixture-payload")
    assert response.status_code == 200 and response.json == payload
    assert case.redactions[-1]["strip_sensitive_fields"] is expected


def test_backend_redaction_failure_is_closed_and_nonstudio_behavior_is_unchanged(backend_case, monkeypatch):
    case = backend_case
    @case.app.get("/fixture-error")
    def error():
        return jsonify(error="fixture-credential-should-not-escape")
    def failure(*args, **kwargs):
        raise RuntimeError("fixture-redactor-failure")
    monkeypatch.setattr("local_studio.redaction.redact_payload", failure)
    client = case.app.test_client()
    closed = client.get("/fixture-error")
    assert closed.status_code == 500 and b"fixture-credential" not in closed.data
    case.environ.pop("MIROFISH_STUDIO_ROOT")
    legacy = client.get("/fixture-error")
    assert legacy.status_code == 200 and legacy.json["error"] == "fixture-credential-should-not-escape"
