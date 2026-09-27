"""Isolated synthetic credentials only; no real service/configuration reads."""

from __future__ import annotations

import ast
import base64
import io
import json
import logging
import os
import sys
import types
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_studio import redaction, config_store


class Codec:
    def encrypt(self, value):
        return "fixture:" + base64.b64encode(value.encode()).decode()

    def decrypt(self, value):
        return base64.b64decode(value.split(":", 1)[1]).decode()


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in redaction._ENV_NAMES | {"MIROFISH_STUDIO_ROOT"}:
        monkeypatch.delenv(name, raising=False)
    redaction.clear_redaction_cache()
    yield
    redaction.clear_redaction_cache()


@pytest.fixture
def store(tmp_path, monkeypatch):
    real_class = config_store.ConfigStore
    instance = real_class(tmp_path, codec=Codec())
    calls = []
    def factory(root):
        assert Path(root).resolve() == tmp_path.resolve(), "Never read a real configuration"
        calls.append(root)
        return instance
    monkeypatch.setattr(config_store, "ConfigStore", factory)
    return instance, calls


def save_model(store, key, *, enabled=True):
    return store.save_model({"name": "Fixture", "key": key, "model": "fixture-model",
                             "base_url": "https://example.invalid/v1", "enabled": enabled})


def test_all_saved_model_and_zep_keys_including_disabled_presets_are_redacted(store, tmp_path):
    instance, calls = store
    keys = ["fixture-model-secret-A", "fixture-disabled-secret-B", "fixture-zep-secret-C"]
    save_model(instance, keys[0])
    save_model(instance, keys[1], enabled=False)
    instance.save_zep({"name": "Fixture Zep", "key": keys[2], "enabled": False})
    text = redaction.redact_text("401 invalid: " + ", ".join(keys), root=tmp_path)
    assert all(key not in text for key in keys)
    assert "401 invalid:" in text and text.count(redaction.REDACTED) == 3
    assert len(calls) == 1


def test_configuration_cache_refreshes_after_edit_and_retains_old_key(store, tmp_path):
    instance, calls = store
    previous = "fixture-old-preset-key"
    current = "fixture-new-preset-key"
    saved = save_model(instance, previous)
    assert previous not in redaction.redact_text(previous, root=tmp_path)
    redaction.redact_text("ordinary message", root=tmp_path)
    assert len(calls) == 1
    instance.save_model({"id": saved["id"], "key": current})
    value = redaction.redact_text(previous + " " + current, root=tmp_path)
    assert previous not in value and current not in value and len(calls) == 2
    instance.delete_model(saved["id"])
    assert current not in redaction.redact_text(current, root=tmp_path)


def test_env_keys_refresh_without_config_changes(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fixture-env-one")
    assert "fixture-env-one" not in redaction.redact_text("bad fixture-env-one")
    monkeypatch.setenv("LLM_API_KEY", "fixture-env-two")
    assert "fixture-env-two" not in redaction.redact_text("bad fixture-env-two")


def test_short_credentials_are_masked_as_tokens_without_destroying_words(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "a")
    assert redaction.redact_text("database rejected a") == "database rejected " + redaction.REDACTED


@pytest.mark.parametrize("text, secret", [
    ('Authorization: Bearer synthetic-header-token', 'synthetic-header-token'),
    ('Proxy-Authorization: Basic dXNlcjpwYXNzd29yZA==', 'dXNlcjpwYXNzd29yZA=='),
    ('{"api_key":"synthetic-json-key"}', 'synthetic-json-key'),
    ("{'api_key': 'synthetic key with spaces'}", 'synthetic key with spaces'),
    ('api_key=synthetic-unquoted-key retry later', 'synthetic-unquoted-key'),
    ('Incorrect API key provided: synthetic-provider-key', 'synthetic-provider-key'),
    ('please remove Bearer synthetic-bearer-token from the header', 'synthetic-bearer-token'),
    ('X-API-Key: synthetic-x-api-key', 'synthetic-x-api-key'),
    ('access_token=synthetic-access-token', 'synthetic-access-token'),
    ('secret_key="synthetic-secret-key"', 'synthetic-secret-key'),
    ('failed sk-fixtureLongStandaloneKey12345', 'sk-fixtureLongStandaloneKey12345'),
    ('failed eyJmaXh0dXJlIjoxfQ.eyJmaXh0dXJlIjoyfQ.c3ludGhldGljc2ln', 'eyJmaXh0dXJlIjoxfQ.eyJmaXh0dXJlIjoyfQ.c3ludGhldGljc2ln'),
])
def test_regex_fallback_for_unsaved_provider_credentials(text, secret):
    result = redaction.redact_text(text)
    assert secret not in result and redaction.REDACTED in result
    assert redaction.redact_text(result) == result


def test_escaped_json_and_url_forms_of_known_credentials_are_redacted():
    secret = 'fixture/key?with="quotes"&x=1'
    encoded = json.dumps(secret)[1:-1]
    url = quote(secret, safe="")
    result = redaction.redact_text("echo " + encoded + " url " + url, extra_secrets=[secret])
    assert encoded not in result and url not in result


@pytest.mark.parametrize("message", [
    "模型 fixture-chat 不存在，请选择其他模型。",
    "HTTP 429: rate limit reached; retry after 30 seconds.",
    "Missing API key; configure it in the local workbench.",
    "Connection refused at http://localhost:11434/v1/models",
    "The model supports 8192 tokens but this request used 9000.",
])
def test_useful_non_secret_error_wording_is_preserved(message):
    assert redaction.redact_text(message) == message


def test_payload_drops_nested_traceback_and_credentials_without_mutating_input():
    secret = "fixture-unsaved-credential"
    original = {"success": False, "error": "Bad key " + secret, "api_key": secret,
                "details": [{"traceback": secret, "stack_trace": "private stack", "code": "bad_key"}],
                "usage": {"max_tokens": 123}, "message": "Try another model."}
    before = json.dumps(original)
    result = redaction.redact_payload(original)
    assert "traceback" not in json.dumps(result) and "stack_trace" not in json.dumps(result)
    assert "api_key" not in result and secret not in json.dumps(result)
    assert result["details"] == [{"code": "bad_key"}]
    assert result["usage"]["max_tokens"] == 123 and result["message"] == "Try another model."
    assert json.dumps(original) == before


def test_traceback_can_be_retained_but_is_still_redacted_when_requested():
    value = redaction.redact_payload({"traceback": "frame fixture-stack-secret"},
                                    extra_secrets=["fixture-stack-secret"], strip_traceback=False)
    assert value == {"traceback": "frame " + redaction.REDACTED}


def test_business_payload_preserves_key_tokens_and_does_not_treat_them_as_secrets():
    payload = {"success": True, "key": "agent-role", "tokens": ["research", "report"],
               "details": {"keys": ["group", "name"], "token": 42},
               "message": "agent-role research report group name"}
    result = redaction.redact_payload(payload, strip_sensitive_fields=False)
    assert result == payload
    assert result is not payload and result["details"] is not payload["details"]


def test_business_payload_still_removes_tracebacks_and_redacts_known_keys(monkeypatch):
    secret = "fixture-business-secret"
    monkeypatch.setenv("LLM_API_KEY", secret)
    payload = {"success": True, "key": "ordinary-id", "data": {"token": secret,
               "traceback": "private stack", "message": "Error for " + secret},
               "description": "Authorization: Bearer fixture-unsaved-bearer"}
    result = redaction.redact_payload(payload, strip_sensitive_fields=False)
    assert result["key"] == "ordinary-id"
    assert result["data"] == {"token": redaction.REDACTED,
                              "message": "Error for " + redaction.REDACTED}
    assert "fixture-unsaved-bearer" not in result["description"]
    assert "traceback" not in json.dumps(result)


def test_unknown_sensitive_values_are_removed_from_other_nested_text():
    payload = {"headers": {"Authorization": "Bearer fixture-header-secret"},
               "error": "request sent Bearer fixture-header-secret"}
    result = redaction.redact_payload(payload)
    assert result["headers"] == {} and "fixture-header-secret" not in json.dumps(result)


def test_unreadable_config_fails_closed_without_exposing_exception(tmp_path, monkeypatch):
    directory = tmp_path / "studio_data"
    directory.mkdir()
    (directory / "config.json").write_text("broken")
    def failure(*args):
        raise RuntimeError("fixture-sensitive-decrypt-detail")
    monkeypatch.setattr(config_store, "ConfigStore", failure)
    assert redaction.redact_text("possibly unknown key", root=tmp_path) == redaction.UNAVAILABLE
    result = redaction.redact_payload({"error": "possibly unknown key", "code": 401}, root=tmp_path)
    assert result == {"error": redaction.UNAVAILABLE, "code": 401}
    assert "fixture-sensitive" not in json.dumps(result)


def test_cyclic_payload_is_bounded():
    payload = {"error": "plain"}
    payload["recursive"] = payload
    result = redaction.redact_payload(payload)
    assert result == {"error": "plain", "recursive": redaction.REDACTED}


def test_formatter_redacts_interpolated_arguments_and_full_exception_stack(monkeypatch):
    secret = "fixture-full-exception-secret"
    monkeypatch.setenv("LLM_API_KEY", secret)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(redaction.RedactingFormatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("redaction-fixture-" + uuid.uuid4().hex)
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    try:
        try:
            raise RuntimeError("provider echoed " + secret)
        except RuntimeError:
            logger.exception("Provider failed for %s", secret)
    finally:
        logger.removeHandler(handler)
        handler.close()
    output = stream.getvalue()
    assert secret not in output and "RuntimeError" in output and "provider echoed" in output
    assert "Traceback" in output and redaction.REDACTED in output


@pytest.mark.parametrize("studio", [True, False])
def test_backend_log_formatter_only_changes_in_studio(tmp_path, monkeypatch, studio):
    # Execute the real logger definitions without its module-level default
    # logger, then direct the tested instance exclusively to a temp directory.
    source_path = Path(__file__).resolve().parents[1] / "backend/app/utils/logger.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "logger" for t in node.targets))]
    module = types.ModuleType("fixture_backend_logger")
    module.__file__ = str(source_path)
    exec(compile(tree, str(source_path), "exec"), module.__dict__)
    module.LOG_DIR = str(tmp_path / "logs")
    module._ensure_utf8_stdout = lambda: None
    if studio:
        monkeypatch.setenv("MIROFISH_STUDIO_ROOT", str(tmp_path))
    secret = "fixture-logger-secret"
    monkeypatch.setenv("LLM_API_KEY", secret)
    name = "fixture-backend-logger-" + uuid.uuid4().hex
    logger = module.setup_logger(name)
    try:
        assert all(isinstance(h.formatter, redaction.RedactingFormatter) == studio for h in logger.handlers)
        logger.error("Provider result %s", secret)
        for handler in logger.handlers:
            handler.flush()
        output = next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")
        assert (secret not in output) == studio
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
