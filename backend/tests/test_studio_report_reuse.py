from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report as api


@pytest.mark.parametrize('force', [False, True])
@pytest.mark.parametrize('status', ['pending', 'processing'])
def test_repeated_report_submission_reuses_active_task(monkeypatch, force, status):
    simulation = SimpleNamespace(project_id='fixture-project', graph_id='fixture-graph')
    project = SimpleNamespace(graph_id='fixture-graph', status=api.ProjectStatus.GRAPH_COMPLETED,
                              simulation_requirement='Synthetic isolated test')
    active = {'task_id': 'fixture-task', 'status': status, 'metadata': {
        'simulation_id': 'fixture-simulation', 'report_id': 'fixture-report'}}
    monkeypatch.setattr(api, 'SimulationManager', lambda: SimpleNamespace(get_simulation=lambda _: simulation))
    monkeypatch.setattr(api.ProjectManager, 'get_project', lambda _: project)
    monkeypatch.setattr(api.SimulationRunner, 'get_run_state', lambda _: SimpleNamespace(runner_status=api.RunnerStatus.COMPLETED))
    monkeypatch.setattr(api.ZepGraphMemoryManager, 'get_updater', lambda _: None)
    monkeypatch.setattr(api, 'TaskManager', lambda: SimpleNamespace(list_tasks=lambda **_: [active]))
    monkeypatch.setattr(api, 'ReportAgent', lambda **_: pytest.fail('Duplicate report generation must never start'))
    app = Flask(__name__)
    app.register_blueprint(api.report_bp, url_prefix='/api/report')
    response = app.test_client().post('/api/report/generate', json={
        'simulation_id': 'fixture-simulation', 'force_regenerate': force})
    assert response.status_code == 200
    assert response.json['data']['report_id'] == 'fixture-report'
    assert response.json['data']['task_id'] == 'fixture-task'
    assert response.json['data']['reused'] is True
