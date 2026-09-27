from types import SimpleNamespace

from flask import Flask

from app.api import simulation as api
from app.models import task as task_module


def test_refresh_finds_persisted_preparation_task(monkeypatch):
    saved = {'task_id': 'latest', 'status': 'processing', 'progress': 45,
             'metadata': {'simulation_id': 'sim_refresh'}}
    monkeypatch.setattr(api, '_check_simulation_prepared', lambda _: (False, {}))
    monkeypatch.setattr(task_module, 'TaskManager', lambda: SimpleNamespace(list_tasks=lambda **_: [saved]))
    app = Flask(__name__)
    app.register_blueprint(api.simulation_bp, url_prefix='/api/simulation')
    response = app.test_client().post('/api/simulation/prepare/status', json={'simulation_id': 'sim_refresh'})
    assert response.json['data']['task_id'] == 'latest'
    assert response.json['data']['status'] == 'processing'
    assert response.json['data']['progress'] == 45


def test_interrupted_preparation_does_not_remain_not_started(monkeypatch):
    monkeypatch.setattr(api, '_check_simulation_prepared', lambda _: (False, {}))
    monkeypatch.setattr(task_module, 'TaskManager', lambda: SimpleNamespace(list_tasks=lambda **_: []))
    monkeypatch.setattr(api, 'SimulationManager', lambda: SimpleNamespace(get_simulation=lambda _: SimpleNamespace(
        status=api.SimulationStatus.PREPARING, error=None)))
    app = Flask(__name__)
    app.register_blueprint(api.simulation_bp, url_prefix='/api/simulation')
    data = app.test_client().post('/api/simulation/prepare/status', json={'simulation_id': 'sim_refresh'}).json['data']
    assert data['status'] == 'failed'
    assert '手动重试' in data['error']
