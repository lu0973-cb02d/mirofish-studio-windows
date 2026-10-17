"""Stage 5: a finished simulation -> ReACT report, retrieval and follow-up chat."""

import json

import pytest


@pytest.fixture
def finished(pipeline):
    return pipeline.completed_simulation()


def test_report_is_generated_from_graph_searches(pipeline, finished):
    generated = pipeline.generate_report(finished["simulation_id"])
    report_id = generated["report_id"]

    report = pipeline.get(f"/api/report/{report_id}")
    assert report["status"] == "completed"
    assert report["outline"]["title"] == "教务改革舆情预测"
    assert [s["title"] for s in report["outline"]["sections"]] == ["舆论格局", "风险与建议"]
    assert "谨慎态度" in report["markdown_content"]
    assert report["markdown_content"].count("谨慎态度") == 2  # one per section

    # Every section ran the three required retrievals against the graph.
    searches = [c for c in pipeline.zep.call_names() if c == "graph.search"]
    assert len(searches) >= 6
    assert pipeline.llm.hits("sub-queries") == 2
    assert not pipeline.llm.unmatched


def test_report_tool_calls_do_not_hide_retrieval_failures(pipeline, finished):
    report_id = pipeline.generate_report(finished["simulation_id"])["report_id"]

    # _execute_tool turns a failing tool into text for the model. A healthy
    # run must never contain that text, or sections are written from nothing.
    log = (pipeline.uploads / "reports" / report_id / "agent_log.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in log.splitlines() if line.strip()]
    results = [e for e in entries if e.get("action") == "tool_result"]
    assert len(results) >= 6
    assert not [e for e in results if "工具执行失败" in json.dumps(e, ensure_ascii=False)]


def test_report_is_reused_until_regeneration_is_forced(pipeline, finished):
    first = pipeline.generate_report(finished["simulation_id"])
    calls = len(pipeline.llm.requests)

    again = pipeline.post("/api/report/generate", {"simulation_id": finished["simulation_id"]})

    assert again["already_generated"] is True
    assert again["report_id"] == first["report_id"]
    assert len(pipeline.llm.requests) == calls
    by_simulation = pipeline.get(f"/api/report/by-simulation/{finished['simulation_id']}")
    assert by_simulation["report_id"] == first["report_id"]


def test_report_is_refused_while_the_simulation_is_running(pipeline, monkeypatch):
    monkeypatch.setenv("STUB_ROUND_DELAY", "0.5")
    ids = pipeline.prepared_simulation()
    pipeline.start(ids["simulation_id"], max_rounds=30)

    response = pipeline.client.post("/api/report/generate", json={"simulation_id": ids["simulation_id"]})

    assert response.status_code == 409
    assert response.get_json()["success"] is False


def test_graph_memory_updates_are_written_back_and_drained(pipeline):
    ids = pipeline.completed_simulation(enable_graph_memory_update=True)

    # Platform activity became Zep episodes before the run was declared done.
    assert pipeline.zep.call_names().count("graph.add") >= 1
    assert pipeline.run_status(ids["simulation_id"])["runner_status"] == "completed"
    # With ingestion drained, reporting is allowed.
    assert pipeline.generate_report(ids["simulation_id"])["status"]["status"] == "completed"
