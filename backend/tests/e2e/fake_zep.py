"""An in-memory stand-in for the slice of Zep Cloud that MiroFish uses.

It follows the SDK's attribute names (``uuid_``, ``with_raw_response`` pages
with a ``zep-next-cursor`` header, the Batch API lifecycle) so the real
services run unchanged. Entity extraction is not simulated: the test supplies
the entities and relations a processed batch should yield.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from types import SimpleNamespace
from typing import Any

from zep_cloud import NotFoundError


def _new_id() -> str:
    return str(uuid.uuid4())


class _Page:
    """Mimic ``client.graph.node.with_raw_response.get_by_graph_id`` pagination."""

    def __init__(self, owner: "FakeZep", kind: str):
        self._owner = owner
        self._kind = kind

    def get_by_graph_id(self, graph_id: str, *, limit: int = 100, cursor: str | None = None):
        graph = self._owner.require_graph(graph_id)
        self._owner.record(f"{self._kind}.get_by_graph_id", graph_id=graph_id, limit=limit, cursor=cursor)
        items = graph["nodes" if self._kind == "node" else "edges"]
        start = int(cursor or 0)
        page = items[start:start + limit]
        headers = {}
        if start + limit < len(items):
            headers["zep-next-cursor"] = str(start + limit)
        return SimpleNamespace(data=page, headers=headers)


class _NodeApi:
    def __init__(self, owner: "FakeZep"):
        self._owner = owner
        self.with_raw_response = _Page(owner, "node")

    def get(self, uuid_: str):
        self._owner.record("node.get", uuid_=uuid_)
        for graph in self._owner.graphs.values():
            for node in graph["nodes"]:
                if node.uuid_ == uuid_:
                    return node
        raise NotFoundError(body={"message": "node not found"})

    def get_edges(self, node_uuid: str):
        self._owner.record("node.get_edges", node_uuid=node_uuid)
        return [e for g in self._owner.graphs.values() for e in g["edges"]
                if e.source_node_uuid == node_uuid]


class _EdgeApi:
    def __init__(self, owner: "FakeZep"):
        self.with_raw_response = _Page(owner, "edge")


class _EpisodeApi:
    def __init__(self, owner: "FakeZep"):
        self._owner = owner

    def get(self, uuid_: str):
        self._owner.record("episode.get", uuid_=uuid_)
        if uuid_ not in self._owner.episodes:
            raise NotFoundError(body={"message": "episode not found"})
        return SimpleNamespace(uuid_=uuid_, processed=True)


class _GraphApi:
    def __init__(self, owner: "FakeZep"):
        self._owner = owner
        self.node = _NodeApi(owner)
        self.edge = _EdgeApi(owner)
        self.episode = _EpisodeApi(owner)

    def create(self, *, graph_id: str, name: str = "", description: str = ""):
        self._owner.record("graph.create", graph_id=graph_id, name=name)
        with self._owner.lock:
            if graph_id in self._owner.graphs:
                raise RuntimeError(f"duplicate graph {graph_id}")
            self._owner.graphs[graph_id] = {"name": name, "ontology": None,
                                            "nodes": [], "edges": [], "episodes": [],
                                            "populated": False}
        return SimpleNamespace(graph_id=graph_id)

    def get(self, graph_id: str):
        self._owner.record("graph.get", graph_id=graph_id)
        self._owner.require_graph(graph_id)
        return SimpleNamespace(graph_id=graph_id)

    def delete(self, graph_id: str):
        self._owner.record("graph.delete", graph_id=graph_id)
        with self._owner.lock:
            self._owner.graphs.pop(graph_id, None)

    def set_ontology(self, *, graph_ids, entities=None, edges=None):
        self._owner.record("graph.set_ontology", graph_ids=list(graph_ids),
                           entities=sorted((entities or {}).keys()),
                           edges=sorted((edges or {}).keys()))
        for graph_id in graph_ids:
            self._owner.require_graph(graph_id)["ontology"] = {
                "entities": sorted((entities or {}).keys()), "edges": sorted((edges or {}).keys())}

    def add(self, *, graph_id: str, type: str = "text", data: str = "", **_kwargs):
        self._owner.record("graph.add", graph_id=graph_id, type=type, data=data)
        graph = self._owner.require_graph(graph_id)
        episode_uuid = _new_id()
        with self._owner.lock:
            self._owner.episodes[episode_uuid] = {"graph_id": graph_id, "data": data}
            graph["episodes"].append(episode_uuid)
        return SimpleNamespace(uuid_=episode_uuid, processed=True)

    def search(self, *, graph_id: str, query: str, limit: int = 10, scope: str = "edges", **_kwargs):
        self._owner.record("graph.search", graph_id=graph_id, query=query, scope=scope, limit=limit)
        graph = self._owner.require_graph(graph_id)
        if scope == "nodes":
            return SimpleNamespace(nodes=graph["nodes"][:limit], edges=None)
        return SimpleNamespace(edges=graph["edges"][:limit], nodes=None)


class _BatchApi:
    def __init__(self, owner: "FakeZep"):
        self._owner = owner

    def create(self, *, metadata=None):
        batch_id = "batch-" + _new_id()[:8]
        self._owner.record("batch.create", batch_id=batch_id)
        with self._owner.lock:
            self._owner.batches[batch_id] = {"metadata": dict(metadata or {}), "items": [],
                                              "status": "draft"}
        return SimpleNamespace(batch_id=batch_id)

    def add(self, *, batch_id: str, items):
        batch = self._owner.batches[batch_id]
        details = []
        with self._owner.lock:
            for item in items:
                episode_uuid = _new_id()
                self._owner.episodes[episode_uuid] = {"graph_id": item.graph_id, "data": item.data}
                detail = SimpleNamespace(sequence_index=len(batch["items"]), episode_uuid=episode_uuid,
                                         source_uuid=episode_uuid, status="succeeded", graph_id=item.graph_id)
                batch["items"].append(detail)
                details.append(detail)
        self._owner.record("batch.add", batch_id=batch_id, count=len(items))
        return details

    def process(self, *, batch_id: str):
        self._owner.record("batch.process", batch_id=batch_id)
        batch = self._owner.batches[batch_id]
        batch["status"] = "succeeded"
        for graph_id in {item.graph_id for item in batch["items"]}:
            self._owner.populate(graph_id)
        return SimpleNamespace(status="queued")

    def get(self, *, batch_id: str):
        batch = self._owner.batches[batch_id]
        succeeded = len(batch["items"]) if batch["status"] == "succeeded" else 0
        return SimpleNamespace(status=batch["status"], metadata=batch["metadata"],
                               progress=SimpleNamespace(percent_complete=100 if succeeded else 0,
                                                        succeeded_items=succeeded))

    def list(self, *, limit: int = 100, cursor=None):
        return SimpleNamespace(batches=[SimpleNamespace(batch_id=b, metadata=v["metadata"])
                                        for b, v in self._owner.batches.items()], next_cursor=None)

    def list_items(self, *, batch_id: str, limit: int = 100, cursor=None):
        return SimpleNamespace(items=list(self._owner.batches[batch_id]["items"]), next_cursor=None)


class FakeZep:
    """Seed with the entities/relations a processed document should produce.

    ``entities``: ``{"name", "label", "summary"}`` dicts.
    ``relations``: ``{"source", "target", "name", "fact"}`` dicts.
    """

    def __init__(self, entities=(), relations=()):
        self.entities = [dict(e) for e in entities]
        self.relations = [dict(r) for r in relations]
        self.graphs: dict[str, dict[str, Any]] = {}
        self.batches: dict[str, dict[str, Any]] = {}
        self.episodes: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict]] = []
        self.lock = threading.RLock()
        self._counter = itertools.count(1)
        self.graph = _GraphApi(self)
        self.batch = _BatchApi(self)

    # ---- helpers -------------------------------------------------------
    def record(self, event: str, /, **details) -> None:
        with self.lock:
            self.calls.append((event, details))

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def require_graph(self, graph_id: str) -> dict[str, Any]:
        graph = self.graphs.get(graph_id)
        if graph is None:
            raise NotFoundError(body={"message": f"graph {graph_id} not found"})
        return graph

    def populate(self, graph_id: str) -> None:
        graph = self.require_graph(graph_id)
        with self.lock:
            if graph["populated"]:
                return
            by_name = {}
            for entity in self.entities:
                node = SimpleNamespace(
                    uuid_=_new_id(), name=entity["name"], labels=["Entity", entity["label"]],
                    summary=entity.get("summary", ""), attributes=dict(entity.get("attributes", {})),
                    created_at="2026-01-01T00:00:00Z")
                graph["nodes"].append(node)
                by_name[entity["name"]] = node
            for relation in self.relations:
                source, target = by_name[relation["source"]], by_name[relation["target"]]
                graph["edges"].append(SimpleNamespace(
                    uuid_=_new_id(), name=relation["name"], fact=relation["fact"],
                    source_node_uuid=source.uuid_, target_node_uuid=target.uuid_, attributes={},
                    created_at="2026-01-01T00:00:00Z", valid_at=None, invalid_at=None, expired_at=None,
                    episodes=[]))
            graph["populated"] = True

    def install(self, monkeypatch) -> "FakeZep":
        """Route every ``get_zep_client`` binding in the backend to this instance."""
        import importlib

        monkeypatch.setattr("app.utils.zep.get_zep_client", lambda *a, **k: self)
        for module in ("graph_builder", "zep_entity_reader", "oasis_profile_generator",
                       "zep_tools", "zep_graph_memory_updater"):
            importlib.import_module(f"app.services.{module}")
            monkeypatch.setattr(f"app.services.{module}.get_zep_client", lambda *a, **k: self)
        return self
