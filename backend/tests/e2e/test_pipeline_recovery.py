"""An engine crash or restart mid-run: no ghost 'running' state, no orphan spend."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services.simulation_runner import SimulationRunner

STUB = Path(__file__).parent / "stub_scripts" / "run_parallel_simulation.py"


def crash_scene(pipeline, ids, *, rounds_done=3, orphan=False):
    """Leave behind exactly what a killed engine leaves on disk."""
    sim = pipeline.uploads / "simulations" / ids["simulation_id"]
    process = None
    if orphan:
        process = subprocess.Popen(
            [sys.executable, str(STUB), "--config", str(sim / "simulation_config.json"), "--max-rounds", "500"],
            cwd=sim, env={**os.environ, "STUB_ROUND_DELAY": "0.3"}, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)  # let it write a few rounds
    (sim / "run_state.json").write_text(json.dumps({
        "runner_status": "running", "current_round": rounds_done, "total_rounds": 10,
        "twitter_running": True, "reddit_running": True, "started_at": "2026-01-01T00:00:00",
        "process_pid": process.pid if process else 999999}), encoding="utf-8")
    state = json.loads((sim / "state.json").read_text(encoding="utf-8"))
    state["status"] = "running"
    (sim / "state.json").write_text(json.dumps(state), encoding="utf-8")
    SimulationRunner._run_states.clear()  # a fresh engine remembers nothing
    return sim, process


def test_an_interrupted_run_is_reported_as_failed_with_a_clear_reason(pipeline):
    ids = pipeline.prepared_simulation()
    crash_scene(pipeline, ids, rounds_done=3)

    status = pipeline.run_status(ids["simulation_id"])

    assert status["runner_status"] == "failed"
    assert status["twitter_running"] is False and status["reddit_running"] is False
    assert "中断" in status["error"] and "3/10" in status["error"]
    # The simulation record agrees, so the studio inventory is not misleading.
    assert pipeline.get(f"/api/simulation/{ids['simulation_id']}")["status"] == "failed"


def test_an_interrupted_run_can_be_rerun_from_the_prepared_state(pipeline):
    ids = pipeline.prepared_simulation()
    sim, _ = crash_scene(pipeline, ids)
    (sim / "twitter").mkdir(exist_ok=True)
    (sim / "twitter" / "actions.jsonl").write_text(
        json.dumps({"round": 3, "agent_id": 0, "agent_name": "旧", "action_type": "CREATE_POST",
                    "action_args": {}, "success": True}) + "\n", encoding="utf-8")
    calls_before = len(pipeline.llm.requests)

    pipeline.start(ids["simulation_id"], max_rounds=2, force=True)
    status = pipeline.wait_run(ids["simulation_id"], until=lambda s: s["runner_status"] == "completed")

    assert status["current_round"] == 2 and status["error"] in (None, "")
    # Only the new run's actions are counted: 2 agents x 2 rounds x 2 platforms.
    assert pipeline.get(f"/api/simulation/{ids['simulation_id']}/actions", limit=100)["count"] == 8
    # Nothing was regenerated: no graph, persona or configuration model calls.
    assert len(pipeline.llm.requests) == calls_before
    assert pipeline.get(f"/api/simulation/{ids['simulation_id']}")["entities_count"] == 3


def test_an_orphaned_simulation_process_is_stopped_so_it_stops_spending(pipeline):
    ids = pipeline.prepared_simulation()
    _, orphan = crash_scene(pipeline, ids, orphan=True)
    try:
        assert orphan.poll() is None, "the stand-in for a surviving process must be running"

        status = pipeline.run_status(ids["simulation_id"])

        assert status["runner_status"] == "failed"
        deadline = time.time() + 10
        while orphan.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert orphan.poll() is not None, "orphaned process kept running"
    finally:
        if orphan.poll() is None:
            orphan.kill()


def test_an_unrelated_process_with_a_recycled_pid_is_left_alone(pipeline):
    ids = pipeline.prepared_simulation()
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sim, _ = crash_scene(pipeline, ids)
        state = json.loads((sim / "run_state.json").read_text(encoding="utf-8"))
        state["process_pid"] = bystander.pid  # the old PID now belongs to someone else
        (sim / "run_state.json").write_text(json.dumps(state), encoding="utf-8")
        SimulationRunner._run_states.clear()

        assert pipeline.run_status(ids["simulation_id"])["runner_status"] == "failed"

        time.sleep(0.5)
        assert bystander.poll() is None, "a process that is not this simulation was terminated"
    finally:
        bystander.kill()


def test_interviews_are_refused_when_the_environment_died_with_the_engine(pipeline):
    ids = pipeline.completed_simulation()
    sim = pipeline.uploads / "simulations" / ids["simulation_id"]
    # Simulate the engine restarting: the stand-in process is gone, but the
    # environment file still says "alive".
    pipeline.post("/api/simulation/close-env", {"simulation_id": ids["simulation_id"], "timeout": 10})
    (sim / "env_status.json").write_text(json.dumps({"status": "alive"}), encoding="utf-8")

    started = time.time()
    response = pipeline.client.post("/api/simulation/interview", json={
        "simulation_id": ids["simulation_id"], "agent_id": 0, "prompt": "还在吗？"})

    assert response.status_code >= 400
    assert time.time() - started < 10, "must fail fast, not after the 60 s IPC timeout"
    assert pipeline.json(pipeline.client.post("/api/simulation/env-status",
                                              json={"simulation_id": ids["simulation_id"]}))["env_alive"] is False
