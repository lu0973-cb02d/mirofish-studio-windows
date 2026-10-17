"""Stage 4: a prepared simulation -> subprocess run, live status, interviews, shutdown."""

import json

import pytest

DONE_WITH_LIVE_ENV = lambda s: s["runner_status"] == "completed"  # noqa: E731


@pytest.fixture
def ready(pipeline):
    return pipeline.prepared_simulation()


def test_run_reports_progress_and_keeps_the_interview_environment(pipeline, ready):
    simulation_id = ready["simulation_id"]

    started = pipeline.start(simulation_id, max_rounds=3)
    assert started["runner_status"] == "running"
    assert started["process_pid"] > 0

    status = pipeline.wait_run(simulation_id, until=DONE_WITH_LIVE_ENV)
    assert status["current_round"] == 3
    assert status["total_rounds"] == 3
    assert status["twitter_completed"] and status["reddit_completed"]
    assert pipeline.json(pipeline.client.post("/api/simulation/env-status",
                                              json={"simulation_id": simulation_id}))["env_alive"] is True

    actions = pipeline.get(f"/api/simulation/{simulation_id}/actions", limit=100)
    # two agents x three rounds x two platforms
    assert actions["count"] == 12
    assert {a["platform"] for a in actions["actions"]} == {"twitter", "reddit"}


def test_interviews_travel_through_the_ipc_channel(pipeline, ready):
    simulation_id = ready["simulation_id"]
    pipeline.start(simulation_id, max_rounds=1)
    pipeline.wait_run(simulation_id, until=DONE_WITH_LIVE_ENV)

    single = pipeline.post("/api/simulation/interview", {
        "simulation_id": simulation_id, "agent_id": 0, "prompt": "你怎么看这项改革？", "platform": "reddit"})
    assert single["result"]["platform"] == "reddit"
    assert "你怎么看" in single["result"]["response"]

    both = pipeline.post("/api/simulation/interview", {
        "simulation_id": simulation_id, "agent_id": 1, "prompt": "你支持吗？"})
    assert set(both["result"]["platforms"]) == {"twitter", "reddit"}

    batch = pipeline.post("/api/simulation/interview/batch", {
        "simulation_id": simulation_id,
        "interviews": [{"agent_id": 0, "prompt": "问题一"}, {"agent_id": 1, "prompt": "问题二"}]})
    assert batch["interviews_count"] == 2


def test_closing_the_environment_stops_interviews(pipeline, ready):
    simulation_id = ready["simulation_id"]
    pipeline.start(simulation_id, max_rounds=1)
    pipeline.wait_run(simulation_id, until=DONE_WITH_LIVE_ENV)

    pipeline.post("/api/simulation/close-env", {"simulation_id": simulation_id, "timeout": 10})

    response = pipeline.client.post("/api/simulation/interview", json={
        "simulation_id": simulation_id, "agent_id": 0, "prompt": "还在吗？"})
    assert response.status_code >= 400
    assert response.get_json()["success"] is False


def test_a_crashing_simulation_is_reported_as_failed(pipeline, ready, monkeypatch):
    monkeypatch.setenv("STUB_CRASH_AT_ROUND", "1")

    pipeline.start(ready["simulation_id"], max_rounds=5)

    status = pipeline.wait_run(ready["simulation_id"], until=lambda s: s["runner_status"] in {"failed", "completed"})
    assert status["runner_status"] == "failed", status
    assert status["error"]


def test_stopping_a_running_simulation(pipeline, ready, monkeypatch):
    monkeypatch.setenv("STUB_ROUND_DELAY", "0.5")
    simulation_id = ready["simulation_id"]
    pipeline.start(simulation_id, max_rounds=40)
    pipeline.wait_run(simulation_id, until=lambda s: s["current_round"] >= 1)

    pipeline.post("/api/simulation/stop", {"simulation_id": simulation_id})

    status = pipeline.wait_run(simulation_id, until=lambda s: s["runner_status"] in {"stopped", "failed"})
    assert status["runner_status"] == "stopped"
    assert status["current_round"] < 40


def test_a_second_start_is_refused_while_running(pipeline, ready, monkeypatch):
    monkeypatch.setenv("STUB_ROUND_DELAY", "0.5")
    simulation_id = ready["simulation_id"]
    pipeline.start(simulation_id, max_rounds=20)

    response = pipeline.client.post("/api/simulation/start", json={"simulation_id": simulation_id, "max_rounds": 20})

    assert response.status_code >= 400
    assert response.get_json()["success"] is False


def test_run_state_is_persisted_for_a_reload(pipeline, ready):
    simulation_id = ready["simulation_id"]
    pipeline.start(simulation_id, max_rounds=2)
    pipeline.wait_run(simulation_id, until=DONE_WITH_LIVE_ENV)

    stored = json.loads((pipeline.uploads / "simulations" / simulation_id / "run_state.json")
                        .read_text(encoding="utf-8"))
    assert stored["runner_status"] == "completed"
    assert stored["current_round"] == 2
