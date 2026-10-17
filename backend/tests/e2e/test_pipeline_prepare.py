"""Stage 3: a built graph -> agent profiles and a full simulation configuration."""

import json
import threading
import time
from pathlib import Path

from conftest import ONTOLOGY, _profile_for, install_standard_routes
from fake_llm import FakeLLM, ProviderError, Route


def prepared(pipeline):
    ids = pipeline.prepared_simulation()
    return ids, Path(pipeline.uploads, "simulations", ids["simulation_id"])


def test_prepare_generates_profiles_and_config_from_the_graph(pipeline):
    ids, sim_dir = prepared(pipeline)

    state = pipeline.get(f"/api/simulation/{ids['simulation_id']}")
    assert state["status"] == "ready"
    assert state["entities_count"] == 3
    assert set(state["entity_types"]) >= {"Student", "Professor", "Organization"}

    # Time/event configuration silently falls back to defaults when the model
    # misbehaves, so prove the model-generated values are what was stored.
    config = json.loads((sim_dir / "simulation_config.json").read_text(encoding="utf-8"))
    assert config["time_config"]["total_simulation_hours"] == 24
    assert config["event_config"]["hot_topics"] == ["教务改革", "选课制度"]
    assert len(config["agent_configs"]) == 3
    assert {a["stance"] for a in config["agent_configs"]} <= {"neutral", "opposing"}
    posters = [p["poster_agent_id"] for p in config["event_config"]["initial_posts"]]
    assert all(isinstance(p, int) for p in posters), "initial posts must be assigned to agents"

    for route in ("time-config", "event-config", "agent-configs"):
        assert pipeline.llm.hits(route) >= 1, route
    assert pipeline.llm.hits("profile") == 3
    assert not pipeline.llm.unmatched


def test_prepare_writes_platform_profile_files(pipeline):
    ids, sim_dir = prepared(pipeline)

    reddit = json.loads((sim_dir / "reddit_profiles.json").read_text(encoding="utf-8"))
    assert {p["name"] for p in reddit} == {"林岚", "周教授", "校学生会"}
    assert all(p["persona"] for p in reddit)
    assert (sim_dir / "twitter_profiles.csv").read_text(encoding="utf-8").count("\n") >= 4

    profiles = pipeline.get(f"/api/simulation/{ids['simulation_id']}/profiles", platform="reddit")
    assert profiles["count"] == 3


def test_prepare_is_idempotent_and_does_not_call_the_model_again(pipeline):
    ids, _ = prepared(pipeline)
    calls = len(pipeline.llm.requests)

    again = pipeline.prepare(ids["simulation_id"])

    assert again["already_prepared"] is True
    assert len(pipeline.llm.requests) == calls


def test_force_regenerate_calls_the_model_again(pipeline):
    ids, _ = prepared(pipeline)
    calls = len(pipeline.llm.requests)

    pipeline.prepare(ids["simulation_id"], force_regenerate=True)

    assert len(pipeline.llm.requests) > calls
    assert pipeline.get(f"/api/simulation/{ids['simulation_id']}")["status"] == "ready"


def test_status_does_not_report_ready_while_a_regeneration_is_running(pipeline):
    ids, _ = prepared(pipeline)
    simulation_id = ids["simulation_id"]
    release = threading.Event()
    # Hold the regeneration inside its first model call.
    pipeline.llm.routes.insert(0, type(pipeline.llm.routes[0])(
        "gate", ("生成时间模拟配置",), lambda payload: (release.wait(30), {})[1]))

    started = pipeline.post("/api/simulation/prepare",
                            {"simulation_id": simulation_id, "force_regenerate": True})
    try:
        for polled in ({"simulation_id": simulation_id},
                       {"simulation_id": simulation_id, "task_id": started["task_id"]}):
            status = pipeline.post("/api/simulation/prepare/status", polled)
            assert status["status"] in {"pending", "processing"}, status
            assert status["already_prepared"] is False
    finally:
        release.set()

    deadline = time.time() + 60
    while time.time() < deadline:
        status = pipeline.post("/api/simulation/prepare/status", {"simulation_id": simulation_id})
        if status["status"] == "ready":
            break
        time.sleep(0.05)
    assert status["status"] == "ready"


def test_preparation_fails_when_the_model_never_answers(pipeline):
    # The ontology step works, then the provider starts rejecting every call
    # (revoked key, exhausted quota). Preparation must stop instead of quietly
    # producing rule-based personas and a default configuration.
    pipeline.llm.route("ontology", contains="本体", respond=ONTOLOGY)
    pipeline.llm.route("provider-down", respond=ProviderError(401, "invalid api key"))
    project_id = pipeline.generate_ontology()["project_id"]
    graph_id = pipeline.build_graph(project_id)["graph_id"]
    simulation_id = pipeline.create_simulation(project_id, graph_id)

    started = pipeline.post("/api/simulation/prepare", {"simulation_id": simulation_id})
    deadline = time.time() + 90
    while time.time() < deadline:
        status = pipeline.post("/api/simulation/prepare/status",
                               {"task_id": started["task_id"], "simulation_id": simulation_id})
        if status["status"] in {"completed", "ready", "failed"}:
            break
        time.sleep(0.1)

    assert status["status"] == "failed", status
    assert "模型" in status["error"]
    state = pipeline.get(f"/api/simulation/{simulation_id}")
    assert state["status"] == "failed"
    assert "模型预设" in state["error"]
    # It stopped at the first unusable step: no configuration was requested.
    assert pipeline.llm.hits("time-config") == 0


def test_partial_model_failures_still_produce_a_usable_simulation(pipeline):
    # One entity's persona fails after retries; the others succeed. This is the
    # accepted degradation: the simulation is ready, with a rule-based persona.
    install_standard_routes(pipeline.llm)
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        text = FakeLLM.prompt_text(payload)
        if "实体名称: 周教授" in text:
            return ProviderError(401, "rejected for this entity")
        return _profile_for(payload)

    pipeline.llm.routes.insert(0, Route("flaky-profile", ("社交媒体用户画像生成专家",), flaky))
    project_id = pipeline.generate_ontology()["project_id"]
    graph_id = pipeline.build_graph(project_id)["graph_id"]
    simulation_id = pipeline.create_simulation(project_id, graph_id)

    pipeline.prepare(simulation_id)

    assert pipeline.get(f"/api/simulation/{simulation_id}")["status"] == "ready"
