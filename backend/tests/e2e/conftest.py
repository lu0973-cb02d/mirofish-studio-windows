"""Pipeline fixtures: the real Flask app and services against fake LLM and Zep."""

from __future__ import annotations

import io
import re
import time
from pathlib import Path

import pytest

from fake_llm import FakeLLM
from fake_zep import FakeZep

# What the fake "Zep extraction" yields for the seed document below.
ENTITIES = [
    {"name": "林岚", "label": "Student", "summary": "林岚是一名关注校园政策的大三学生。"},
    {"name": "周教授", "label": "Professor", "summary": "周教授负责教务改革方案的论证。"},
    {"name": "校学生会", "label": "Organization", "summary": "校学生会组织学生讨论并向校方反馈。"},
]
RELATIONS = [
    {"source": "林岚", "target": "周教授", "name": "ASKS", "fact": "林岚向周教授询问改革细则。"},
    {"source": "校学生会", "target": "林岚", "name": "REPRESENTS", "fact": "校学生会代表林岚等学生发声。"},
]
SEED_DOCUMENT = (
    "某高校计划调整选课与考核制度。学生会收集了学生意见，周教授对方案作了说明，"
    "林岚等同学在论坛发帖表达关切。\n" * 12
)
REQUIREMENT = "推演这项教务改革在学生群体中的舆论走向。"

ONTOLOGY = {
    "entity_types": [
        {"name": "Student", "description": "在校学生", "attributes": [
            {"name": "major", "type": "text", "description": "所学专业"}], "examples": ["林岚"]},
        {"name": "Professor", "description": "高校教师", "attributes": [
            {"name": "department", "type": "text", "description": "所属院系"}], "examples": ["周教授"]},
    ],
    "edge_types": [
        {"name": "ASKS", "description": "提问或求助", "source_targets": [
            {"source": "Student", "target": "Professor"}], "attributes": []},
    ],
    "analysis_summary": "材料围绕一次教务改革引发的校园讨论。",
}


def _profile_for(payload) -> dict:
    text = FakeLLM.prompt_text(payload)
    group = "机构/群体" in text
    return {"bio": "用于测试的社交媒体简介。", "persona": "一段连贯的人设描述，用于驱动模拟中的发言。",
            "age": 30 if group else 20, "gender": "other" if group else "female", "mbti": "ISTJ",
            "country": "中国", "profession": "学生", "interested_topics": ["教务改革", "选课"]}


def _agent_configs_for(payload) -> dict:
    ids = [int(i) for i in re.findall(r'"agent_id":\s*(\d+)', FakeLLM.prompt_text(payload))]
    return {"agent_configs": [
        {"agent_id": i, "activity_level": 0.7, "posts_per_hour": 1.0, "comments_per_hour": 2.0,
         "active_hours": [19, 20, 21, 22], "response_delay_min": 1, "response_delay_max": 10,
         "sentiment_bias": -0.2, "stance": "opposing" if i % 2 else "neutral", "influence_weight": 1.0}
        for i in ids]}


def install_standard_routes(llm: FakeLLM) -> FakeLLM:
    """Responses for every LLM step up to a prepared simulation."""
    llm.route("ontology", contains="本体", respond=ONTOLOGY)
    llm.route("profile", contains="社交媒体用户画像生成专家", respond=_profile_for)
    llm.route("time-config", contains="生成时间模拟配置", respond={
        "total_simulation_hours": 24, "minutes_per_round": 60, "agents_per_hour_min": 1,
        "agents_per_hour_max": 2, "peak_hours": [19, 20, 21, 22], "off_peak_hours": [0, 1, 2, 3, 4, 5],
        "morning_hours": [6, 7, 8], "work_hours": list(range(9, 19)), "reasoning": "测试用时间配置"})
    llm.route("event-config", contains="生成事件配置", respond={
        "hot_topics": ["教务改革", "选课制度"], "narrative_direction": "从质疑逐渐转向理性讨论",
        "initial_posts": [{"content": "学校公布了新的选课方案，大家怎么看？", "poster_type": "Student"},
                          {"content": "方案说明会将于下周举行。", "poster_type": "Professor"}],
        "reasoning": "测试用事件配置"})
    llm.route("agent-configs", contains="为每个实体生成社交媒体活动配置", respond=_agent_configs_for)
    return llm


def _section_for(payload) -> str:
    """A ReACT section writer: three tool calls, then a Final Answer."""
    turns = sum(1 for m in payload["messages"] if m.get("role") == "assistant")
    tools = ['{"name": "quick_search", "parameters": {"query": "选课制度", "limit": 5}}',
             '{"name": "panorama_search", "parameters": {"query": "学生群体的态度"}}',
             '{"name": "insight_forge", "parameters": {"query": "谁在反对这项改革"}}']
    if turns < len(tools):
        return f"我需要先检索更多信息。\n<tool_call>{tools[turns]}</tool_call>"
    return "Final Answer:\n学生群体对改革持谨慎态度，林岚等人担心选课自由度下降；周教授的说明有助于缓和争议。"


def install_report_routes(llm: FakeLLM) -> FakeLLM:
    llm.route("report-outline", contains="【预测场景设定】", respond={
        "title": "教务改革舆情预测", "summary": "学生态度由质疑转向理性讨论。",
        "sections": [{"title": "舆论格局"}, {"title": "风险与建议"}]})
    llm.route("sub-queries", contains="分解为多个可以在模拟世界中独立观察的子问题",
              respond={"sub_queries": ["谁在讨论这项改革", "为什么学生关注选课"]})
    llm.route("report-section", contains="正在撰写报告的一个章节", respond=_section_for)
    return llm


class Pipeline:
    """Convenience wrapper around the Flask test client."""

    def __init__(self, client, llm: FakeLLM, zep: FakeZep, uploads: Path):
        self.client, self.llm, self.zep, self.uploads = client, llm, zep, uploads

    # -- diagnostics ------------------------------------------------------
    def explain(self, response) -> str:
        detail = response.get_data(as_text=True)[:1500]
        if self.llm.unmatched:
            detail += "\n[FakeLLM unmatched prompt]\n" + self.llm.unmatched[0].text[:1500]
        return f"HTTP {response.status_code}: {detail}"

    def json(self, response, expect=200):
        assert response.status_code == expect, self.explain(response)
        body = response.get_json()
        assert body.get("success") is True, self.explain(response)
        return body["data"]

    def post(self, path, payload=None, expect=200):
        return self.json(self.client.post(path, json=payload or {}), expect)

    def get(self, path, expect=200, **query):
        return self.json(self.client.get(path, query_string=query), expect)

    # -- stages -----------------------------------------------------------
    def wait_task(self, task_id: str, *, timeout: float = 60.0, poll: str = "/api/graph/task/") -> dict:
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            last = self.get(poll + task_id)
            if last["status"] in {"completed", "failed"}:
                return last
            time.sleep(0.05)
        raise AssertionError(f"task {task_id} did not finish: {last}")

    def generate_ontology(self, name="教务改革") -> dict:
        response = self.client.post(
            "/api/graph/ontology/generate",
            data={"simulation_requirement": REQUIREMENT, "project_name": name,
                  "files": (io.BytesIO(SEED_DOCUMENT.encode("utf-8")), "seed.md")},
            content_type="multipart/form-data")
        return self.json(response)

    def build_graph(self, project_id: str) -> dict:
        started = self.post("/api/graph/build", {"project_id": project_id})
        task = self.wait_task(started["task_id"])
        assert task["status"] == "completed", task
        return task["result"]

    def create_simulation(self, project_id: str, graph_id: str) -> str:
        data = self.post("/api/simulation/create", {"project_id": project_id, "graph_id": graph_id})
        return data["simulation_id"]

    def prepare(self, simulation_id: str, **options) -> dict:
        started = self.post("/api/simulation/prepare", {"simulation_id": simulation_id, **options})
        if started.get("already_prepared"):
            return started
        deadline = time.time() + 60
        while time.time() < deadline:
            status = self.post("/api/simulation/prepare/status",
                               {"task_id": started["task_id"], "simulation_id": simulation_id})
            if status["status"] in {"completed", "ready", "failed"}:
                assert status["status"] != "failed", status
                return status
            time.sleep(0.05)
        raise AssertionError("simulation preparation did not finish")

    def start(self, simulation_id: str, **options) -> dict:
        return self.post("/api/simulation/start", {"simulation_id": simulation_id, **options})

    def run_status(self, simulation_id: str) -> dict:
        return self.get(f"/api/simulation/{simulation_id}/run-status")

    def wait_run(self, simulation_id: str, *, until, timeout: float = 60.0) -> dict:
        """Poll run-status until ``until(status)`` is true."""
        deadline = time.time() + timeout
        status = {}
        while time.time() < deadline:
            status = self.run_status(simulation_id)
            if until(status):
                return status
            time.sleep(0.1)
        raise AssertionError(f"simulation {simulation_id} did not reach the expected state: {status}")

    def completed_simulation(self, **start_options) -> dict:
        """A prepared simulation that has run to completion (interview env alive)."""
        ids = self.prepared_simulation()
        self.start(ids["simulation_id"], max_rounds=2, **start_options)
        self.wait_run(ids["simulation_id"], until=lambda s: s["runner_status"] == "completed")
        return ids

    def generate_report(self, simulation_id: str, *, timeout: float = 90.0) -> dict:
        install_report_routes(self.llm)
        started = self.post("/api/report/generate", {"simulation_id": simulation_id})
        if started.get("already_generated"):
            return started
        deadline = time.time() + timeout
        status = {}
        while time.time() < deadline:
            status = self.post("/api/report/generate/status",
                               {"task_id": started["task_id"], "simulation_id": simulation_id})
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert status.get("status") == "completed", status
        # The report is marked completed a moment before its task record is;
        # callers that immediately re-request must see the settled state.
        self.wait_task(started["task_id"], timeout=timeout)
        return {**started, "status": status}

    def prepared_simulation(self) -> dict:
        """Run ontology -> graph -> create -> prepare and return the identifiers."""
        install_standard_routes(self.llm)
        project_id = self.generate_ontology()["project_id"]
        graph_id = self.build_graph(project_id)["graph_id"]
        simulation_id = self.create_simulation(project_id, graph_id)
        self.prepare(simulation_id)
        return {"project_id": project_id, "graph_id": graph_id, "simulation_id": simulation_id}


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM().start()
    # Loopback must never travel through a developer's or CI runner's proxy.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    yield llm
    llm.stop()


@pytest.fixture
def fake_zep(monkeypatch):
    return FakeZep(ENTITIES, RELATIONS).install(monkeypatch)


@pytest.fixture
def pipeline(tmp_path, monkeypatch, fake_llm, fake_zep):
    """The real application wired to temporary storage and the two fakes."""
    from app import create_app
    from app.config import Config
    from app.models.project import ProjectManager
    from app.models.task import TaskManager
    from app.services.report_agent import ReportManager
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner

    for name in ("MIROFISH_STUDIO_ROOT", "MIROFISH_DATA_ROOT", "ZEP_API_URL"):
        monkeypatch.delenv(name, raising=False)

    uploads = tmp_path / "uploads"
    (uploads / "simulations").mkdir(parents=True)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(uploads / "simulations"))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(uploads / "projects"))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(uploads / "simulations"))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(uploads / "simulations"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(uploads / "reports"))
    # OASIS cannot run in CI; the stub honours the same process contract.
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(Path(__file__).parent / "stub_scripts"))
    monkeypatch.setattr(TaskManager, "_instance", None)
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(Config, "LLM_BASE_URL", fake_llm.base_url)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "fake-model")
    monkeypatch.setattr(Config, "ZEP_API_KEY", "zep-test-key-not-a-secret")

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield Pipeline(client, fake_llm, fake_zep, uploads)

    SimulationRunner.cleanup_all_simulations()
    SimulationRunner._run_states.clear()
    SimulationRunner._processes.clear()
