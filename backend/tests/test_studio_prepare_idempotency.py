"""Prepare submission tests; graph reads, models, files and workers are fakes."""

import copy
import threading
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.models import task as task_module
from app.services.simulation_manager import SimulationStatus


RealThread = threading.Thread


class FakeTasks:
    def __init__(self):
        self.records = {}
        self.lock = threading.Lock()

    def create_task(self, task_type, metadata=None):
        identifier = str(uuid.uuid4())
        with self.lock:
            self.records[identifier] = {"task_id": identifier, "task_type": task_type,
                                        "metadata": copy.deepcopy(metadata or {}), "status": "pending", "progress": 0}
        return identifier

    def list_tasks(self, task_type=None):
        with self.lock:
            return [copy.deepcopy(task) for task in self.records.values()
                    if task_type is None or task["task_type"] == task_type]

    def update_task(self, identifier, **updates):
        if "status" in updates:
            updates["status"] = updates["status"].value
        with self.lock:
            self.records[identifier].update(updates)

    def fail_task(self, identifier, error):
        self.update_task(identifier, status=task_module.TaskStatus.FAILED, error=error)

    def complete_task(self, identifier, result):
        self.update_task(identifier, status=task_module.TaskStatus.COMPLETED, progress=100, result=result)


@pytest.fixture
def prepare_env(monkeypatch):
    tasks = FakeTasks()
    fixture = SimpleNamespace(tasks=tasks, workers=[], reads=[], saves=[], prepare_calls=[],
                              save_hook=None, start_error=None, prepare_error=None)

    def state(identifier):
        result = SimpleNamespace(simulation_id=identifier, project_id="project-fixture", graph_id="graph-fixture",
                                 status=SimulationStatus.CREATED, entities_count=0, entity_types=[], error=None)
        result.to_simple_dict = lambda: {"simulation_id": identifier, "status": result.status.value}
        return result
    fixture.states = {identifier: state(identifier) for identifier in ("sim-a", "sim-b")}

    class Manager:
        def get_simulation(self, identifier):
            return fixture.states.get(identifier)

        def _save_simulation_state(self, selected):
            fixture.saves.append((selected.simulation_id, selected.status))
            if fixture.save_hook:
                fixture.save_hook(selected)

        def prepare_simulation(self, **kwargs):
            fixture.prepare_calls.append(kwargs)
            if fixture.prepare_error:
                error, fixture.prepare_error = fixture.prepare_error, None
                raise error
            selected = fixture.states[kwargs["simulation_id"]]
            kwargs["progress_callback"]("reading", 50, "fixture progress", current=1, total=2)
            selected.status = SimulationStatus.READY
            return selected

    class Reader:
        def filter_defined_entities(self, **kwargs):
            fixture.reads.append(("graph", kwargs))
            assert any(task["status"] == "processing" for task in tasks.list_tasks())
            return SimpleNamespace(filtered_count=3, entity_types=["Person"])

    class DeferredThread:
        def __init__(self, *, target, daemon):
            self.target = target
            assert daemon is True

        def start(self):
            if fixture.start_error:
                error, fixture.start_error = fixture.start_error, None
                raise error
            fixture.workers.append(self.target)

    def extracted_text(_cls, project_id):
        fixture.reads.append(("document", project_id))
        return "fixture source text"

    monkeypatch.setattr(simulation_api, "_prepare_submission_locks", {})
    monkeypatch.setattr(simulation_api, "SimulationManager", Manager)
    monkeypatch.setattr(simulation_api, "ZepEntityReader", Reader)
    monkeypatch.setattr(simulation_api, "_check_simulation_prepared", lambda identifier: (
        fixture.states[identifier].status == SimulationStatus.READY, {"profiles_count": 3}))
    monkeypatch.setattr(simulation_api.ProjectManager, "get_project", classmethod(
        lambda _cls, _identifier: SimpleNamespace(simulation_requirement="fixture requirement")))
    monkeypatch.setattr(simulation_api.ProjectManager, "get_extracted_text", classmethod(extracted_text))
    monkeypatch.setattr(task_module, "TaskManager", lambda: tasks)
    monkeypatch.setattr(threading, "Thread", DeferredThread)
    fixture.app = Flask(__name__)

    def submit(identifier="sim-a", **params):
        with fixture.app.test_request_context("/api/simulation/prepare", method="POST",
                                               json={"simulation_id": identifier, **params}):
            result = simulation_api.prepare_simulation()
            if isinstance(result, tuple):
                response, status = result
            else:
                response, status = result, result.status_code
            return response.get_json(), status
    fixture.submit = submit
    return fixture


def test_task_is_registered_and_request_returns_before_document_or_zep_reads(prepare_env):
    fixture = prepare_env
    body, status = fixture.submit()
    assert status == 200
    identifier = body["data"]["task_id"]
    assert fixture.tasks.records[identifier]["status"] == "pending"
    assert fixture.states["sim-a"].status == SimulationStatus.PREPARING
    assert fixture.reads == [] and fixture.prepare_calls == []
    assert len(fixture.workers) == 1
    fixture.workers[0]()
    assert [entry[0] for entry in fixture.reads] == ["document", "graph"]
    assert fixture.tasks.records[identifier]["status"] == "completed"
    assert fixture.states["sim-a"].entities_count == 3


@pytest.mark.parametrize("force", [False, True])
def test_concurrent_submissions_reuse_one_task_even_with_force(prepare_env, force):
    fixture = prepare_env
    claimed = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    responses = {}

    def block_first_save(selected):
        if not claimed.is_set():
            claimed.set()
            assert release.wait(3)
    fixture.save_hook = block_first_save
    first = RealThread(target=lambda: responses.setdefault("first", fixture.submit()))
    def second_submit():
        second_started.set()
        responses["second"] = fixture.submit(force_regenerate=force)
    second = RealThread(target=second_submit)
    first.start()
    try:
        assert claimed.wait(2)
        second.start()
        assert second_started.wait(2)
        second.join(0.05)
        assert second.is_alive()
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    first_body, first_status = responses["first"]
    second_body, second_status = responses["second"]
    assert first_status == second_status == 200
    assert first_body["data"]["task_id"] == second_body["data"]["task_id"]
    assert second_body["data"]["reused"] is True
    assert len(fixture.tasks.records) == len(fixture.workers) == 1
    assert fixture.reads == []


@pytest.mark.parametrize("task_status", [task_module.TaskStatus.PENDING, task_module.TaskStatus.PROCESSING])
@pytest.mark.parametrize("force", [False, True])
def test_active_task_wins_over_old_completed_artifacts_and_force(prepare_env, task_status, force):
    fixture = prepare_env
    identifier = fixture.tasks.create_task("simulation_prepare", {"simulation_id": "sim-a"})
    fixture.tasks.update_task(identifier, status=task_status)
    fixture.states["sim-a"].status = SimulationStatus.READY
    body, status = fixture.submit(force_regenerate=force)
    assert status == 200 and body["data"]["task_id"] == identifier
    assert body["data"]["already_prepared"] is False and body["data"]["reused"] is True
    assert fixture.workers == [] and fixture.reads == []


def test_failed_worker_allows_a_new_explicit_retry_without_changing_old_failure(prepare_env):
    fixture = prepare_env
    fixture.prepare_error = RuntimeError("fixture preparation failure")
    first_body, status = fixture.submit()
    first_id = first_body["data"]["task_id"]
    assert status == 200
    fixture.workers[0]()
    assert fixture.tasks.records[first_id]["status"] == "failed"
    assert fixture.states["sim-a"].status == SimulationStatus.FAILED
    retry_body, retry_status = fixture.submit()
    retry_id = retry_body["data"]["task_id"]
    assert retry_status == 200 and retry_id != first_id
    assert retry_body["data"]["reused"] is False
    fixture.workers[1]()
    assert fixture.tasks.records[first_id]["status"] == "failed"
    assert fixture.tasks.records[retry_id]["status"] == "completed"
    assert fixture.states["sim-a"].status == SimulationStatus.READY


def test_already_prepared_result_is_reused_without_new_work(prepare_env):
    fixture = prepare_env
    fixture.states["sim-a"].status = SimulationStatus.READY
    body, status = fixture.submit()
    assert status == 200 and body["data"]["already_prepared"] is True
    assert body["data"]["status"] == "ready"
    assert fixture.tasks.records == {} and fixture.workers == [] and fixture.reads == []


def test_force_can_regenerate_a_finished_simulation_when_no_task_is_active(prepare_env):
    fixture = prepare_env
    fixture.states["sim-a"].status = SimulationStatus.READY
    body, status = fixture.submit(force_regenerate=True)
    assert status == 200 and body["data"]["already_prepared"] is False
    assert len(fixture.tasks.records) == len(fixture.workers) == 1


def test_thread_start_failure_is_terminal_and_does_not_block_retry(prepare_env):
    fixture = prepare_env
    fixture.start_error = RuntimeError("fixture thread launch failure")
    _, status = fixture.submit()
    assert status == 500
    failed_id = next(iter(fixture.tasks.records))
    assert fixture.tasks.records[failed_id]["status"] == "failed"
    assert fixture.states["sim-a"].status == SimulationStatus.FAILED
    retry_body, retry_status = fixture.submit()
    assert retry_status == 200 and retry_body["data"]["task_id"] != failed_id
    assert len(fixture.workers) == 1


def test_state_save_failure_does_not_leave_a_permanent_pending_claim(prepare_env):
    fixture = prepare_env
    def fail_once(_state):
        fixture.save_hook = None
        raise OSError("fixture state write failure")
    fixture.save_hook = fail_once
    _, status = fixture.submit()
    assert status == 500
    failed_id = next(iter(fixture.tasks.records))
    assert fixture.tasks.records[failed_id]["status"] == "failed"
    body, status = fixture.submit()
    assert status == 200 and body["data"]["task_id"] != failed_id


def test_submission_lock_is_per_simulation_not_global(prepare_env):
    fixture = prepare_env
    claimed = threading.Event()
    release = threading.Event()
    responses = {}
    def block_a(selected):
        if selected.simulation_id == "sim-a":
            claimed.set()
            assert release.wait(3)
    fixture.save_hook = block_a
    first = RealThread(target=lambda: responses.setdefault("a", fixture.submit("sim-a")))
    second = RealThread(target=lambda: responses.setdefault("b", fixture.submit("sim-b")))
    first.start()
    try:
        assert claimed.wait(2)
        second.start()
        second.join(2)
        assert not second.is_alive()
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert responses["a"][1] == responses["b"][1] == 200
    assert responses["a"][0]["data"]["task_id"] != responses["b"][0]["data"]["task_id"]
    assert len(fixture.tasks.records) == 2


def test_force_rejects_string_boolean_before_any_mutation(prepare_env):
    body, status = prepare_env.submit(force_regenerate="false")
    assert status == 400 and body["success"] is False
    assert prepare_env.tasks.records == {} and prepare_env.saves == []
