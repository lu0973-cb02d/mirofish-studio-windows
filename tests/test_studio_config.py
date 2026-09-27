"""Storage and network-boundary tests; no real provider credentials or calls."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from local_studio import connectivity
from local_studio.config_store import ConfigError, ConfigStore, DPAPICodec, normalize_base_url


class FixtureCodec:
    """Deliberately non-production codec, explicitly injected into every test."""

    def encrypt(self, plaintext):
        return "fixture:" + base64.b64encode(plaintext.encode()).decode()

    def decrypt(self, ciphertext):
        if not ciphertext.startswith("fixture:"):
            raise ValueError("unexpected fixture")
        return base64.b64decode(ciphertext.split(":", 1)[1]).decode()


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path, codec=FixtureCodec())


def model_payload(**overrides):
    return {"name": "测试模型", "base_url": "https://example.invalid/v1", "model": "chat-test",
            "key": "fixture-key-never-real-1234", **overrides}


def test_public_never_contains_secrets_or_ciphertext(store):
    model = store.save_model(model_payload())
    zep = store.save_zep({"name": "测试项目", "key": "fixture-zep-never-real-5678", "group": "alpha"})
    store.activate_model(model["id"])
    store.activate_zep(zep["id"])
    exposed = json.dumps([model, zep, store.public()], ensure_ascii=False)
    persisted = store.path.read_text(encoding="utf-8")
    for secret in ("fixture-key-never-real-1234", "fixture-zep-never-real-5678"):
        assert secret not in exposed
        assert secret not in persisted
    assert "key_enc" not in exposed and "fixture:" not in exposed
    assert model["key_hint"] == "••••1234"
    assert zep["key_hint"] == "••••5678"
    assert store.runtime_model()["key"] == model_payload()["key"]
    assert store.runtime_zep()["group"] == "alpha"
    assert all("key" not in preset for preset in store.public()["presets"])


def test_omitted_or_empty_key_preserves_and_explicit_clear_erases(store):
    saved = store.save_model(model_payload())
    store.save_model({"id": saved["id"], "name": "改名"})
    store.save_model({"id": saved["id"], "key": "   "})
    assert store.runtime_model(saved["id"])["key"] == model_payload()["key"]
    cleared = store.save_model({"id": saved["id"], "clear_key": True})
    assert not cleared["has_key"] and not cleared["key_hint"]
    assert store.runtime_model(saved["id"])["key"] == ""


def test_zep_partial_edit_preserves_group_and_secret(store):
    saved = store.save_zep({"name": "Zep", "key": "test-zep-secret", "group": "project-1"})
    store.save_zep({"id": saved["id"], "name": "新名字", "key": ""})
    current = store.runtime_zep(saved["id"])
    assert current["group"] == "project-1"
    assert current["key"] == "test-zep-secret"
    assert store.save_zep({"name": "短密钥", "key": "abc"})["key_hint"] == "••••"


@pytest.mark.parametrize("bad_key", [None, False, 123, ["secret"], {"ciphertext": "secret"}])
def test_secret_type_confusion_rejected(store, bad_key):
    with pytest.raises(ConfigError, match="API Key"):
        store.save_model(model_payload(key=bad_key))
    assert store.public()["models"] == []


@pytest.mark.parametrize("address", [
    "file:///secrets", "javascript:alert(1)", "https://name:password@example.invalid/v1",
    "https://example.invalid/v1?key=secret", "https://example.invalid/#fragment",
    "https://example.invalid/?", "https://example.invalid/#", "https://example.invalid:bad/v1",
    "https://exa mple.invalid/v1", "https://example.invalid\\@other.invalid/v1", "https:///v1",
])
def test_url_rejects_credential_leaks_and_ambiguous_addresses(address):
    with pytest.raises(ConfigError) as error:
        normalize_base_url(address)
    assert "password" not in str(error.value) and "secret" not in str(error.value)


@pytest.mark.parametrize(("address", "normalized"), [
    (" https://example.invalid/v1/chat/completions/ ", "https://example.invalid/v1"),
    ("https://example.invalid/v1/models", "https://example.invalid/v1"),
    ("https://example.invalid/compatible-mode/v1/", "https://example.invalid/compatible-mode/v1"),
    ("http://localhost:11434/v1", "http://localhost:11434/v1"),
    ("http://[::1]:1234/v1", "http://[::1]:1234/v1"),
])
def test_url_normalizes_only_endpoint_suffixes(address, normalized):
    assert normalize_base_url(address) == normalized


def test_activation_deletion_and_candidate_order(store):
    blank = store.save_model(model_payload(model="", key=""))
    with pytest.raises(ConfigError, match="模型"):
        store.activate_model(blank["id"])
    first = store.save_zep({"name": "first", "key": "first-fixture-key", "group": "one"})
    second = store.save_zep({"name": "second", "key": "second-fixture-key", "group": "two"})
    store.save_zep({"name": "disabled", "key": "disabled-fixture-key", "enabled": False})
    store.save_zep({"name": "empty"})
    store.activate_zep(second["id"])
    assert [item["id"] for item in store.zep_candidates()] == [second["id"], first["id"]]
    assert store.set_auto_zep(False) is False
    assert store.public()["auto_zep"] is False
    store.save_zep({"id": second["id"], "enabled": False})
    assert store.public()["active_zep_id"] == ""
    with pytest.raises(ConfigError):
        store.runtime_zep(second["id"])
    store.activate_zep(first["id"])
    store.delete_zep(first["id"])
    assert store.public()["active_zep_id"] == ""


def test_migration_deduplicates_env_and_saved_models_and_is_idempotent(store):
    env = ('LLM_API_KEY="migration-model-fixture"\nLLM_BASE_URL=https://example.invalid/v1/\n'
           'LLM_MODEL_NAME=test-chat\nZEP_API_KEY=migration-zep-fixture\n')
    legacy = {"provider": "primary", "keys": {
        "primary": {"key": "migration-model-fixture", "base": "https://example.invalid/v1", "model": "test-chat"},
        "other": {"key": "migration-other-fixture", "base": "https://other.invalid/v1", "model": "other-chat"}},
        "zep_profiles": [{"name": "project", "key": "migration-zep-fixture", "enabled": True}],
        "active_zep": "project", "auto_zep": False}
    (store.root / ".env").write_text(env, encoding="utf-8")
    legacy_text = json.dumps(legacy)
    (store.root / "manager_config.json").write_text(legacy_text, encoding="utf-8")
    counts = store.import_legacy()
    assert counts == {"models": 2, "zep": 1, "skipped": 0, "already_imported": False}
    assert store.runtime_model()["name"] == "primary"
    assert store.runtime_zep()["name"] == "project"
    assert store.public()["auto_zep"] is False
    second = store.import_legacy()
    assert second["models"] == second["zep"] == 0 and second["already_imported"]
    assert (store.root / ".env").read_text(encoding="utf-8") == env
    assert (store.root / "manager_config.json").read_text(encoding="utf-8") == legacy_text
    assert "migration-model-fixture" not in store.path.read_text(encoding="utf-8")


def test_migration_does_not_replace_existing_selection_or_preferences(store):
    current = store.save_model(model_payload(name="新界面已选模型"))
    store.activate_model(current["id"])
    store.set_auto_zep(False)
    (store.root / ".env").write_text(
        "LLM_BASE_URL=https://old.invalid/v1\nLLM_MODEL_NAME=old\nLLM_API_KEY=old-fixture-key", encoding="utf-8")
    (store.root / "manager_config.json").write_text('{"auto_zep":true}', encoding="utf-8")
    assert store.import_legacy()["models"] == 1
    assert store.public()["active_model_id"] == current["id"]
    assert store.public()["auto_zep"] is False


def test_migration_vault_failure_does_not_mark_import_complete(store):
    class BrokenCodec(FixtureCodec):
        def encrypt(self, plaintext):
            raise RuntimeError("private-material-do-not-display")
    (store.root / ".env").write_text("ZEP_API_KEY=migration-fixture-key", encoding="utf-8")
    broken = ConfigStore(store.root, codec=BrokenCodec())
    with pytest.raises(ConfigError) as error:
        broken.import_legacy()
    assert "private-material" not in str(error.value)
    assert not broken.path.exists()
    assert store.import_legacy()["zep"] == 1


def test_public_rejects_tampered_unmasked_key_hint(store):
    store.save_model(model_payload())
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["models"][0]["key_hint"] = "unmasked-private-fixture-secret"
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        store.public()
    assert "unmasked-private" not in str(error.value)


def test_corrupt_storage_is_preserved_and_failed_save_keeps_previous(store, monkeypatch):
    store.save_model(model_payload())
    original = store.path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(PermissionError("private-provider-body")))
    with pytest.raises(ConfigError) as error:
        store.save_model(model_payload(name="second"))
    assert "private-provider-body" not in str(error.value)
    assert store.path.read_bytes() == original
    assert not list(store.directory.glob(".config-*.tmp"))
    store.path.write_text('{"bad":"fixture-secret"}', encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        store.save_zep({"name": "Zep"})
    assert "fixture-secret" not in str(error.value)
    assert store.path.read_text() == '{"bad":"fixture-secret"}'


def test_separate_instances_do_not_lose_concurrent_thread_updates(tmp_path):
    def save(index):
        ConfigStore(tmp_path, codec=FixtureCodec()).save_model(model_payload(name=f"model-{index}"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(24)))
    assert len(ConfigStore(tmp_path, codec=FixtureCodec()).public()["models"]) == 24


def test_separate_processes_do_not_lose_updates(tmp_path):
    script = """
import sys
from local_studio.config_store import ConfigStore
class UnusedCodec:
    def encrypt(self, value): raise AssertionError('No keys in process test')
    def decrypt(self, value): raise AssertionError('No keys in process test')
store=ConfigStore(sys.argv[1], codec=UnusedCodec())
for i in range(12):
    store.save_model({'name':sys.argv[2]+str(i),'base_url':'http://localhost:11434/v1','model':'fixture'})
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(number)],
                                 cwd=Path(__file__).resolve().parents[1],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                 for number in range(2)]
    for process in processes:
        _, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr.decode(errors="replace")
    assert len(ConfigStore(tmp_path, codec=FixtureCodec()).public()["models"]) == 24


@pytest.mark.skipif(os.name != "nt", reason="Windows-only DPAPI integration")
def test_windows_dpapi_roundtrip_and_corruption_fail_closed(tmp_path):
    secure = ConfigStore(tmp_path)
    saved = secure.save_model(model_payload())
    assert secure.runtime_model(saved["id"])["key"] == model_payload()["key"]
    raw = secure.path.read_text(encoding="utf-8")
    assert "dpapi:v1:" in raw and model_payload()["key"] not in raw
    with pytest.raises(ConfigError):
        DPAPICodec().decrypt("plaintext-is-not-supported")


def test_default_codec_has_no_nonwindows_plaintext_fallback(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    with pytest.raises(ConfigError, match="Windows"):
        DPAPICodec()


def mock_transport(monkeypatch, handler):
    real_client = httpx.Client
    settings = []

    def client_factory(**kwargs):
        settings.append(kwargs)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(connectivity.httpx, "Client", client_factory)
    return settings


def test_discover_deduplicates_models_and_refuses_echoed_credentials(monkeypatch):
    key = model_payload()["key"]
    def handler(request):
        assert request.url.path == "/v1/models"
        assert request.headers["Authorization"] == "Bearer " + key
        return httpx.Response(200, json={"data": [{"id": "chat-a"}, {"id": "chat-a"}, {"id": "chat-b"},
                                                 {"id": key}, {"id": "bad\nmodel"}, {"id": 7}]})
    settings = mock_transport(monkeypatch, handler)
    result = connectivity.discover_models(model_payload())
    assert result["ok"] and result["models"] == ["chat-a", "chat-b"]
    assert key not in json.dumps(result)
    assert settings[0]["follow_redirects"] is False
    assert 0 < settings[0]["timeout"].connect <= 12
    assert 0 < settings[0]["timeout"].read <= 40
    assert 0 < settings[0]["timeout"].write <= 10


def test_discover_supports_optional_models_array_and_manual_fallback(monkeypatch):
    responses = iter([httpx.Response(200, json={"models": ["chat-a", {"name": "chat-b"}]}),
                      httpx.Response(404, json={"error": "provider-secret"})])
    mock_transport(monkeypatch, lambda _: next(responses))
    assert connectivity.discover_models(model_payload())["models"] == ["chat-a", "chat-b"]
    result = connectivity.discover_models(model_payload())
    assert not result["ok"] and "手动" in result["message"] and "provider-secret" not in str(result)


@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
def test_network_failures_never_expose_provider_body_or_follow_redirect(monkeypatch, status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://other.invalid/steal"},
                              json={"error": {"message": model_payload()["key"]}})
    mock_transport(monkeypatch, handler)
    result = connectivity.test_model(model_payload())
    assert not result["ok"] and result["status"] == status
    assert model_payload()["key"] not in str(result)
    assert len(requests) == 1


def test_model_test_uses_tiny_constant_prompt_and_bounded_reasoning_retry(monkeypatch):
    sent = []
    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"param": "max_tokens", "message": "private"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Never show provider content"}}]})
    mock_transport(monkeypatch, handler)
    result = connectivity.test_model(model_payload())
    assert result["ok"] and len(sent) == 2
    assert sent[0]["max_tokens"] == sent[1]["max_completion_tokens"] == 16
    assert sent[0]["messages"] == [{"role": "user", "content": "Reply OK."}]
    assert "Never show" not in str(result)


def test_transport_exception_details_are_sanitized(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("api-key=private-error-secret", request=request)
    mock_transport(monkeypatch, handler)
    result = connectivity.test_model(model_payload())
    assert not result["ok"] and "private-error-secret" not in str(result)


def test_zep_checks_documented_read_only_endpoint_without_mutations(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url).startswith("https://api.getzep.com/api/v2/graph/list-all?")
        assert request.url.params["pageSize"] == "1"
        assert request.headers["Authorization"] == "Api-Key zep-fixture-secret"
        return httpx.Response(200, json={"graphs": [], "row_count": 0, "total_count": 0})
    mock_transport(monkeypatch, handler)
    result = connectivity.test_zep({"key": "zep-fixture-secret"})
    assert result["ok"] and len(requests) == 1
    assert "zep-fixture-secret" not in str(result)


def test_zep_and_model_reject_wrong_success_schema(monkeypatch):
    mock_transport(monkeypatch, lambda _: httpx.Response(200, json={"error": "secret-error"}))
    assert not connectivity.test_zep({"key": "zep-fixture"})["ok"]
    result = connectivity.test_model(model_payload())
    assert not result["ok"] and "secret-error" not in str(result)


def test_zep_empty_account_matches_optional_sdk_graphs_schema(monkeypatch):
    mock_transport(monkeypatch, lambda _: httpx.Response(200, json={"graphs": None, "total_count": 0}))
    assert connectivity.test_zep({"key": "zep-fixture"})["ok"]


def test_local_model_can_discover_without_authorization_header(monkeypatch):
    def handler(request):
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})
    mock_transport(monkeypatch, handler)
    result = connectivity.discover_models(model_payload(base_url="http://localhost:11434/v1", key=""))
    assert result["ok"]
