"""Stage 1-2: documents -> ontology -> knowledge graph, through the real HTTP API."""

from conftest import ONTOLOGY


def register_ontology_route(llm):
    llm.route("ontology", contains="本体", respond=ONTOLOGY)


def test_ontology_generation_creates_a_project(pipeline):
    register_ontology_route(pipeline.llm)

    data = pipeline.generate_ontology()

    names = [t["name"] for t in data["ontology"]["entity_types"]]
    assert {"Student", "Professor"} <= set(names)
    # The generator guarantees catch-all types even if the model omits them.
    assert names[-2:] == ["Person", "Organization"]
    assert data["total_text_length"] > 100
    assert not pipeline.llm.unmatched

    project = pipeline.get(f"/api/graph/project/{data['project_id']}")
    assert project["status"] == "ontology_generated"
    assert project["simulation_requirement"]


def test_graph_build_populates_zep_and_completes_the_project(pipeline):
    register_ontology_route(pipeline.llm)
    project_id = pipeline.generate_ontology()["project_id"]

    result = pipeline.build_graph(project_id)

    graph_id = result["graph_id"]
    assert (result["node_count"], result["edge_count"]) == (3, 2)
    assert result["chunk_count"] >= 1
    assert result["zep_batch_id"].startswith("batch-")
    # Ordering matters: the ontology must exist before documents are ingested.
    names = pipeline.zep.call_names()
    assert names.index("graph.create") < names.index("graph.set_ontology") < names.index("batch.process")
    project = pipeline.get(f"/api/graph/project/{project_id}")
    assert project["status"] == "graph_completed"
    assert project["graph_id"] == graph_id

    data = pipeline.get(f"/api/graph/data/{graph_id}")
    assert data["node_count"] == 3 and data["edge_count"] == 2
    assert {edge["source_node_name"] for edge in data["edges"]} == {"林岚", "校学生会"}


def test_graph_build_refuses_a_project_without_an_ontology(pipeline):
    response = pipeline.client.post("/api/graph/build", json={"project_id": "proj_missing"})
    assert response.status_code == 404
