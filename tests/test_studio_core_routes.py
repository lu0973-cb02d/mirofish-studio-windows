"""The /studio-api/core surface, through the real Flask app with a fake engine."""

import io
import json
import threading
import types

import httpx
import pytest

from core_fixtures import OTHER_SEED, App
from local_studio import server
from local_studio.config_store import ConfigStore
from local_studio.core_update import ReleaseSource
from test_studio_core_release import release_item, source
from test_studio_core_switch import FakeEngine
from test_studio_server import BASE, HEADERS, FixtureCodec


@pytest.fixture
def desk(tmp_path):
    app = App(tmp_path)
    dist = app.root / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>bundled ui</html>", encoding="utf-8")
    engine = FakeEngine(app.store, running=False)
    published = {"items": []}
    bundles = {}

    def handler(request):
        if request.url.path.endswith(".zip"):
            return httpx.Response(200, content=bundles[request.url.path.rsplit("/", 1)[1]])
        return httpx.Response(200, json=published["items"])

    flask = server.create_app(root=app.root, store=ConfigStore(tmp_path / "cfg", codec=FixtureCodec()),
                              engine=engine, core=app.store, core_source=source(handler))
    flask.config["TESTING"] = True
    return types.SimpleNamespace(app=app, engine=engine, client=flask.test_client(), published=published,
                                 bundles=bundles, flask=flask)


def call(desk, path, *, method="GET", body=None, headers=None, **kwargs):
    return desk.client.open(path, method=method, base_url=BASE, headers=HEADERS if headers is None else headers,
                            json=body, **kwargs)


def offer(desk, version="1.1.1"):
    desk.published["items"] = [release_item(version)]
    desk.bundles[f"mirofish-core-{version}.zip"] = desk.app.bundle(version).read_bytes()


def test_status_describes_the_running_core_and_the_update_channel(desk):
    data = call(desk, "/studio-api/core").json["data"]
    assert data["enabled"] is True
    assert data["running"] == {"version": "1.1.0", "upstream_commit": "bundled-commit",
                               "source": "bundled", "notice": ""}
    assert data["installed"] == [] and data["can_rollback"] is False and data["last_check"] is None


def test_every_core_route_requires_the_workbench_header(desk):
    for method, path in [("GET", "/studio-api/core"), ("POST", "/studio-api/core/check"),
                         ("POST", "/studio-api/core/install"), ("POST", "/studio-api/core/activate"),
                         ("POST", "/studio-api/core/rollback"), ("POST", "/studio-api/core/import")]:
        assert call(desk, path, method=method, body={}, headers={}).status_code == 403, path


def test_check_install_activate_and_rollback_end_to_end(desk):
    offer(desk)
    checked = call(desk, "/studio-api/core/check", method="POST", body={}).json["data"]
    assert checked["available"] is True and checked["latest"] == "1.1.1"
    assert call(desk, "/studio-api/core").json["data"]["last_check"]["latest"] == "1.1.1"

    assert call(desk, "/studio-api/core/install", method="POST", body={"version": "1.1.1"}).json["data"] == {"installed": "1.1.1"}
    assert call(desk, "/").get_data(as_text=True) == "<html>bundled ui</html>", "installing must not change the UI"

    switched = call(desk, "/studio-api/core/activate", method="POST", body={"version": "1.1.1"}).json["data"]
    assert switched["running"]["version"] == "1.1.1" and switched["restarted"] is False
    assert call(desk, "/studio-api/core").json["data"]["last_check"] is None, "the update was applied; no stale offer"
    assert call(desk, "/").get_data(as_text=True) == "<html>core 1.1.1</html>", "the core ships its own UI"
    assert call(desk, "/studio-api/core").json["data"]["running"]["source"] == "downloaded"

    back = call(desk, "/studio-api/core/rollback", method="POST", body={}).json["data"]
    assert back["running"]["version"] == "1.1.0"
    assert call(desk, "/").get_data(as_text=True) == "<html>bundled ui</html>"


def test_installing_requires_a_prior_check_for_that_version(desk):
    offer(desk)
    response = call(desk, "/studio-api/core/install", method="POST", body={"version": "1.1.1"})
    assert response.status_code == 400 and "请先检查更新" in response.json["error"]
    call(desk, "/studio-api/core/check", method="POST", body={})
    assert call(desk, "/studio-api/core/install", method="POST", body={"version": "9.9.9"}).status_code == 400


@pytest.mark.parametrize("body", [{}, {"version": ""}, {"version": "../x"}, {"version": 5}, "text"])
def test_versions_in_requests_are_validated(desk, body):
    for path in ("/studio-api/core/install", "/studio-api/core/activate"):
        assert call(desk, path, method="POST", body=body).status_code == 400


def test_activating_while_a_task_runs_is_refused_and_changes_nothing(desk):
    offer(desk)
    call(desk, "/studio-api/core/check", method="POST", body={})
    call(desk, "/studio-api/core/install", method="POST", body={"version": "1.1.1"})
    desk.engine.running, desk.engine.busy = True, True

    response = call(desk, "/studio-api/core/activate", method="POST", body={"version": "1.1.1"})

    assert response.status_code == 409
    assert call(desk, "/studio-api/core").json["data"]["running"]["source"] == "bundled"


def test_a_signed_bundle_can_be_imported_from_a_file(desk):
    data = desk.app.bundle("1.1.1").read_bytes()
    response = call(desk, "/studio-api/core/import", method="POST", headers=HEADERS,
                    data={"bundle": (io.BytesIO(data), "mirofish-core-1.1.1.zip")}, content_type="multipart/form-data")
    assert response.json["data"] == {"installed": "1.1.1"}
    assert desk.app.store.installed_versions() == ["1.1.1"]
    assert list(desk.app.store.incoming.iterdir()) == []


def test_importing_a_forged_or_broken_file_is_refused_without_a_trace(desk):
    forged = desk.app.bundle("1.1.1", seed=OTHER_SEED).read_bytes()
    response = call(desk, "/studio-api/core/import", method="POST",
                    data={"bundle": (io.BytesIO(forged), "x.zip")}, content_type="multipart/form-data")
    assert response.status_code == 400 and "签名无效" in response.json["error"]
    response = call(desk, "/studio-api/core/import", method="POST",
                    data={"bundle": (io.BytesIO(b"nope"), "x.zip")}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert call(desk, "/studio-api/core/import", method="POST", body={}).status_code == 400
    assert desk.app.store.installed_versions() == [] and list(desk.app.store.incoming.iterdir()) == []


def test_a_larger_upload_is_allowed_only_for_the_import_route(desk):
    big = io.BytesIO(b"x" * (2 * 1024 * 1024))
    imported = call(desk, "/studio-api/core/import", method="POST",
                    data={"bundle": (big, "x.zip")}, content_type="multipart/form-data")
    assert imported.status_code == 400 and "无法打开" in imported.json["error"]   # reached the handler, not 413
    assert call(desk, "/studio-api/models", method="POST", body={"name": "x" * (2 * 1024 * 1024)}).status_code == 413


def test_error_messages_never_leak_filesystem_paths(desk):
    response = call(desk, "/studio-api/core/activate", method="POST", body={"version": "1.1.1"})
    assert response.status_code == 400
    assert str(desk.app.tmp) not in response.get_data(as_text=True)


def test_without_a_public_key_nothing_can_be_installed_or_activated(tmp_path):
    keyless = App(tmp_path, public_hex="")
    engine = FakeEngine(keyless.store, running=False)
    flask = server.create_app(root=keyless.root, store=ConfigStore(tmp_path / "cfg", codec=FixtureCodec()),
                              engine=engine, core=keyless.store)
    client = flask.test_client()
    status = client.get("/studio-api/core", base_url=BASE, headers=HEADERS).json["data"]
    assert status["enabled"] is False
    response = client.post("/studio-api/core/import", base_url=BASE, headers=HEADERS,
                           data={"bundle": (io.BytesIO(keyless.bundle("1.1.1").read_bytes()), "x.zip")},
                           content_type="multipart/form-data")
    assert response.status_code == 400 and "公钥" in response.json["error"]
