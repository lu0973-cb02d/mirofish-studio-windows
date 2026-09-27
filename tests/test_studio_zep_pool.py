"""Offline tests: account isolation, bounded rotation, and uncertain writes."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from zep_cloud import NotFoundError
from zep_cloud.core.api_error import ApiError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_studio.zep_pool import ZepPool, ZepPoolError, get_health


def entry(identity, group="", *, enabled=True):
    return {"id": identity, "name": identity, "group": group, "key": "secret-" + identity, "enabled": enabled}


class Store:
    def __init__(self, entries, auto=True):
        self.entries = entries
        self.active = entries[0]["id"]
        self.auto = auto

    def zep_candidates(self):
        return sorted([e.copy() for e in self.entries if e["enabled"]], key=lambda e: e["id"] != self.active)

    def public(self):
        return {"auto_zep": self.auto, "active_zep_id": self.active, "zep": [{"id": e["id"]} for e in self.entries]}


class FakeResource:
    def __init__(self, sdk, path):
        self.sdk, self.path = sdk, path

    def __getattr__(self, name):
        path = self.path + (name,)
        if name in {"node", "edge", "episode", "with_raw_response"}:
            return FakeResource(self.sdk, path)

        def call(*args, **kwargs):
            self.sdk.calls.append((path, args, kwargs))
            handler = self.sdk.handlers.get(path)
            if isinstance(handler, BaseException):
                raise handler
            if callable(handler):
                return handler(*args, **kwargs)
            if handler is not None:
                return handler
            if path == ("graph", "create"):
                return SimpleNamespace(graph_id=kwargs["graph_id"])
            if path == ("graph", "get"):
                return SimpleNamespace(graph_id=args[0] if args else kwargs["graph_id"])
            if path == ("graph", "add"):
                return SimpleNamespace(uuid_="episode-" + self.sdk.identity)
            if path == ("batch", "create"):
                return SimpleNamespace(batch_id="batch-" + self.sdk.identity, metadata=kwargs.get("metadata"))
            if path == ("batch", "list"):
                return SimpleNamespace(batches=[], next_cursor=None, source=self.sdk.identity)
            return SimpleNamespace(source=self.sdk.identity)

        return call


class FakeSDK:
    def __init__(self, identity):
        self.identity, self.calls, self.handlers = identity, [], {}
        self.graph = FakeResource(self, ("graph",))
        self.batch = FakeResource(self, ("batch",))


def setup_pool(tmp_path, entries=None, auto=True):
    store = Store(entries or [entry("a"), entry("b")], auto=auto)
    clients = {e["key"]: FakeSDK(e["id"]) for e in store.entries}
    clock = [1_000.0]
    pool = ZepPool(tmp_path, store, lambda key: clients[key], clock=lambda: clock[0])
    return pool, store, clients, clock


def error(code, headers=None):
    return ApiError(status_code=code, body={"message": "unsafe provider body: secret-a"}, headers=headers)


def paths(sdk):
    return [c[0] for c in sdk.calls]


@pytest.mark.parametrize("code", [401, 403, 429])
def test_new_graph_uses_next_account_only_after_definite_rejection(tmp_path, code):
    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "create")] = error(code)
    result = pool.client().graph.create(graph_id="new")
    assert result.graph_id == "new"
    assert paths(clients["secret-a"]) == [("graph", "create")]
    assert paths(clients["secret-b"]) == [("graph", "create")]
    state = json.loads((tmp_path / "studio_data/zep_bindings.json").read_text())
    assert state["graphs"]["new"]["group"] == "key:b"
    assert store.active == "a"  # A different graph must keep its own choice.


def test_existing_graph_stays_in_its_account_when_active_selection_changes(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    pool.client().graph.create(graph_id="existing")
    store.active = "b"
    result = pool.client().graph.get("existing")
    assert result.graph_id == "existing"
    assert paths(clients["secret-a"])[-1] == ("graph", "get")
    assert clients["secret-b"].calls == []


@pytest.mark.parametrize("group", ["", "different-accounts"])
def test_existing_graph_never_fails_over_to_an_unrelated_account(tmp_path, group):
    pool, store, clients, clock = setup_pool(tmp_path, [entry("a", group), entry("b", "other")])
    client = pool.client()
    client.graph.create(graph_id="existing")
    clients["secret-a"].handlers[("graph", "get")] = error(401)
    with pytest.raises(ApiError) as caught:
        client.graph.get("existing")
    assert caught.value.status_code == 401
    assert clients["secret-b"].calls == []


def test_same_account_rotation_verifies_graph_then_tracks_episode(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path, [entry("a", "shared"), entry("b", "shared")])
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("graph", "add")] = error(429, {"Retry-After": "30"})
    episode = client.graph.add(graph_id="graph", data="test", type="text")
    assert episode.uuid_ == "episode-b"
    assert paths(clients["secret-b"]) == [("graph", "get"), ("graph", "add")]
    pool.client().graph.episode.get(uuid_=episode.uuid_)
    assert paths(clients["secret-b"])[-1] == ("graph", "episode", "get")
    health = get_health(tmp_path)
    assert next(e for e in health["entries"] if e["id"] == "a")["cooldown_until"] == 1_030


def test_declared_shared_group_does_not_allow_writes_to_an_invisible_graph(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path, [entry("a", "shared"), entry("b", "shared")])
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("graph", "add")] = error(403)
    clients["secret-b"].handlers[("graph", "get")] = NotFoundError(body={"message": "hidden"})
    with pytest.raises(NotFoundError):
        client.graph.add(graph_id="graph", data="test", type="text")
    assert paths(clients["secret-b"]) == [("graph", "get")]


def test_invisible_sibling_can_be_skipped_for_a_third_visible_sibling(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path, [entry(k, "shared") for k in "abc"])
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("graph", "add")] = error(403)
    clients["secret-b"].handlers[("graph", "get")] = error(404)
    assert client.graph.add(graph_id="graph", data="test", type="text").uuid_ == "episode-c"
    assert paths(clients["secret-b"]) == [("graph", "get")]
    assert paths(clients["secret-c"]) == [("graph", "get"), ("graph", "add")]


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("secret-a"), error(500), error(408)])
def test_uncertain_write_is_never_replayed_and_sdk_retries_are_off(tmp_path, failure):
    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "create")] = failure
    with pytest.raises(Exception) as caught:
        pool.client().graph.create(graph_id="uncertain", request_options={"max_retries": 99, "timeout_in_seconds": 8})
    assert "secret-a" not in str(caught.value)
    assert paths(clients["secret-a"]) == [("graph", "create")]
    assert clients["secret-b"].calls == []
    assert clients["secret-a"].calls[0][2]["request_options"] == {"max_retries": 0, "timeout_in_seconds": 8}
    state = json.loads((tmp_path / "studio_data/zep_bindings.json").read_text())
    assert state["graphs"]["uncertain"]["group"] == "key:a"


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("secret-a"), error(503)])
def test_read_transient_error_can_rotate_within_same_account(tmp_path, failure):
    pool, store, clients, clock = setup_pool(tmp_path, [entry("a", "shared"), entry("b", "shared")])
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("graph", "search")] = failure
    assert client.graph.search(graph_id="graph", query="test").source == "b"
    assert paths(clients["secret-b"]) == [("graph", "get"), ("graph", "search")]


def test_auto_rotation_can_be_disabled(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path, auto=False)
    clients["secret-a"].handlers[("graph", "create")] = error(429)
    with pytest.raises(ApiError):
        pool.client().graph.create(graph_id="graph")
    assert clients["secret-b"].calls == []


def test_cooldown_skips_bad_key_for_subsequent_new_graph(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "create")] = error(401)
    pool.client().graph.create(graph_id="first")
    pool.client().graph.create(graph_id="second")
    assert len(clients["secret-a"].calls) == 1
    assert len(clients["secret-b"].calls) == 2
    clock[0] += 301
    pool.client().graph.create(graph_id="third")
    assert len(clients["secret-a"].calls) == 2


def test_key_edit_releases_cooldown_after_process_restart(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "create")] = error(401)
    pool.client().graph.create(graph_id="first")
    store.entries[0]["key"] = "replacement-a"
    clients["replacement-a"] = FakeSDK("a-new")
    restarted = ZepPool(tmp_path, store, lambda key: clients[key], clock=lambda: clock[0])
    restarted.client().graph.create(graph_id="new")
    assert len(clients["replacement-a"].calls) == 1
    assert get_health(tmp_path)["entries"][0]["status"] == "available"


def test_ownership_survives_process_restart(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    pool.client().graph.create(graph_id="graph")
    store.active = "b"
    restarted = ZepPool(tmp_path, store, lambda key: clients[key])
    restarted.client().graph.get("graph")
    assert clients["secret-b"].calls == []


def test_current_batch_api_and_episode_polling_follow_graph_ownership(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    client = pool.client()
    clients["secret-a"].handlers[("graph", "create")] = error(401)
    client.graph.create(graph_id="graph")
    batch = client.batch.create(metadata={"graph_id": "graph", "mirofish_operation_id": "op"})
    assert batch.batch_id == "batch-b"
    clients["secret-b"].handlers[("batch", "add")] = [SimpleNamespace(episode_uuid="batch-ep", graph_id="graph")]
    client.batch.add(batch_id=batch.batch_id, items=[SimpleNamespace(graph_id="graph")])
    client.batch.process(batch_id=batch.batch_id)
    pool.client().graph.episode.get("batch-ep")
    assert paths(clients["secret-b"])[-4:] == [("batch", "create"), ("batch", "add"), ("batch", "process"), ("graph", "episode", "get")]


def test_batch_reconciliation_context_is_per_facade(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    first, second = pool.client(), pool.client()
    first.graph.create(graph_id="a-graph")
    first.batch.create(metadata={"graph_id": "a-graph"})
    store.active = "b"
    second.graph.create(graph_id="b-graph")
    second.batch.create(metadata={"graph_id": "b-graph"})
    assert first.batch.list().source == "a"
    assert second.batch.list().source == "b"


def test_concurrent_graphs_do_not_share_mutable_affinity(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    client = pool.client()
    client.graph.create(graph_id="a-graph")
    store.active = "b"
    client.graph.create(graph_id="b-graph")

    def run(graph):
        client.batch.create(metadata={"graph_id": graph})
        return client.batch.list().source

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, graph) for graph in ("a-graph", "b-graph")]
        assert [f.result() for f in futures] == ["a", "b"]


def test_raw_pagination_maps_nodes_edges_and_referenced_episodes(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("graph", "edge", "with_raw_response", "get_by_graph_id")] = SimpleNamespace(
        data=[SimpleNamespace(uuid_="edge", source_node_uuid="source", target_node_uuid="target", episodes=["episode"])],
        headers={"zep-next-cursor": "cursor"},
    )
    result = client.graph.edge.with_raw_response.get_by_graph_id("graph", limit=100)
    assert result.headers["zep-next-cursor"] == "cursor"
    store.active = "b"
    new_client = pool.client()
    new_client.graph.node.get(uuid_="target")
    new_client.graph.edge.get("edge")
    new_client.graph.episode.get(uuid_="episode")
    assert clients["secret-b"].calls == []


def test_search_response_maps_all_resource_types(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("graph", "search")] = SimpleNamespace(
        nodes=[SimpleNamespace(uuid_="node")], edges=[SimpleNamespace(uuid_="edge")], episodes=[SimpleNamespace(uuid_="ep")]
    )
    client.graph.search(graph_id="graph", query="test")
    store.active = "b"
    for kind, identity in (("node", "node"), ("edge", "edge"), ("episode", "ep")):
        getattr(pool.client().graph, kind).get(uuid_=identity)
    assert clients["secret-b"].calls == []


def test_unknown_existing_graph_cannot_roam_between_accounts(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "get")] = error(401)
    with pytest.raises(ApiError):
        pool.client().graph.get("unknown")
    assert clients["secret-b"].calls == []


def test_mixed_account_request_is_blocked_before_network(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    client = pool.client()
    client.graph.create(graph_id="a-graph")
    store.active = "b"
    client.graph.create(graph_id="b-graph")
    with pytest.raises(ZepPoolError, match="不同"):
        client.graph.set_ontology(entities={}, graph_ids=["a-graph", "b-graph"])
    assert paths(clients["secret-a"]) == paths(clients["secret-b"]) == [("graph", "create")]


def test_corrupt_binding_journal_fails_closed(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    directory = tmp_path / "studio_data"
    directory.mkdir()
    (directory / "zep_bindings.json").write_text("broken", encoding="utf-8")
    with pytest.raises(ZepPoolError, match="备份"):
        pool.client().graph.get("graph")
    assert not any(c.calls for c in clients.values())


def test_errors_and_health_never_expose_credentials_or_provider_payloads(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path, auto=False)
    clients["secret-a"].handlers[("graph", "create")] = error(403)
    with pytest.raises(ApiError) as caught:
        pool.client().graph.create(graph_id="graph")
    health = get_health(tmp_path)
    assert "secret-" not in str(caught.value)
    assert "unsafe provider" not in str(caught.value)
    assert "secret-" not in json.dumps(health)
    assert "fingerprint" not in json.dumps(health)
    for path in (tmp_path / "studio_data").glob("*.json"):
        assert "secret-" not in path.read_text()


def test_explicit_key_bypasses_pool_even_when_studio_is_enabled(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    from app.utils import zep
    from local_studio import zep_pool

    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.setenv("MIROFISH_STUDIO_ROOT", str(tmp_path))
    calls = []
    monkeypatch.setattr(zep, "Zep", lambda **kwargs: calls.append(kwargs) or SimpleNamespace())
    monkeypatch.setattr(zep_pool, "get_studio_zep_client", lambda *_: pytest.fail("explicit key must bypass pool"))
    zep.clear_zep_client_cache()
    zep.get_zep_client("explicit-key")
    assert calls[0]["api_key"] == "explicit-key"
    zep.clear_zep_client_cache()


def test_default_key_uses_studio_pool(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    from app.utils import zep
    from local_studio import zep_pool

    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.setenv("MIROFISH_STUDIO_ROOT", str(tmp_path))
    pooled = object()
    monkeypatch.setattr(zep_pool, "get_studio_zep_client", lambda *_: pooled)
    assert zep.get_zep_client() is pooled


def test_uncertain_graph_creation_can_be_reconciled_immediately(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "backend"))
    from app.services import graph_builder

    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "create")] = httpx.ReadTimeout("lost reply")
    client = pool.client()
    monkeypatch.setattr(graph_builder, "get_zep_client", lambda _: client)
    monkeypatch.setattr(graph_builder.Config, "ZEP_API_KEY", "test-only")
    service = graph_builder.GraphBuilderService()
    assert service.create_graph("test", graph_id="uncertain") == "uncertain"
    assert paths(clients["secret-a"]) == [("graph", "create"), ("graph", "get")]
    assert clients["secret-b"].calls == []


def test_uncertain_batch_creation_reconciles_in_original_account(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    client = pool.client()
    client.graph.create(graph_id="graph")
    clients["secret-a"].handlers[("batch", "create")] = error(503)
    with pytest.raises(ApiError):
        client.batch.create(metadata={"graph_id": "graph"})
    store.active = "b"
    assert client.batch.list().source == "a"
    assert clients["secret-b"].calls == []


def test_key_group_edit_does_not_reassign_existing_graph(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path, [entry("a", "original"), entry("b", "different")])
    client = pool.client()
    client.graph.create(graph_id="graph")
    store.entries[0]["group"] = "different"
    with pytest.raises(ZepPoolError, match="绑定"):
        client.graph.get("graph")
    assert paths(clients["secret-a"]) == [("graph", "create")]
    assert clients["secret-b"].calls == []


def test_unknown_graph_write_verifies_visibility_before_sending(tmp_path):
    pool, store, clients, clock = setup_pool(tmp_path)
    clients["secret-a"].handlers[("graph", "get")] = error(404)
    with pytest.raises(ApiError):
        pool.client().graph.add(graph_id="unknown", data="private", type="text")
    assert paths(clients["secret-a"]) == [("graph", "get")]
    assert clients["secret-b"].calls == []


def test_studio_with_all_keys_deleted_does_not_fall_back_to_old_env_key(monkeypatch, tmp_path):
    from local_studio import config_store, zep_pool

    directory = tmp_path / "studio_data"
    directory.mkdir()
    (directory / "config.json").write_text("{}")
    monkeypatch.setattr(config_store, "ConfigStore", lambda _: SimpleNamespace(zep_candidates=lambda: []))
    with pytest.raises(ZepPoolError, match="没有已启用"):
        zep_pool.get_studio_zep_client(tmp_path, 60, lambda *_: pytest.fail("must not use old env key"))
