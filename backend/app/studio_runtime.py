"""Private, local-only Studio integration; no credentials are returned."""
import os
import threading
from urllib.parse import urlsplit

from .config import Config
from .models.task import TaskManager
from .services.simulation_runner import SimulationRunner, RunnerStatus


_config_apply_lock = threading.RLock()


def health_snapshot():
    active_tasks = [t for t in TaskManager().list_tasks()
                    if t['status'] in {'pending', 'processing'}]
    active_runs, interview_ids = [], []
    for simulation_id, state in list(SimulationRunner._run_states.items()):
        if state.runner_status in {RunnerStatus.RUNNING, RunnerStatus.STARTING,
                                  RunnerStatus.PAUSED, RunnerStatus.STOPPING}:
            active_runs.append(simulation_id)
        process = SimulationRunner._processes.get(simulation_id)
        if (state.runner_status == RunnerStatus.COMPLETED and process is not None
                and process.poll() is None):
            interview_ids.append(simulation_id)
    with _config_apply_lock:
        return {'busy': bool(active_tasks or active_runs),
                'pending_tasks': len(active_tasks), 'active_simulations': len(active_runs),
                'interview_ids': interview_ids, 'interview_count': len(interview_ids),
                'runtime_model_id': os.environ.get('MIROFISH_MODEL_ID', ''),
                'runtime_revision': os.environ.get('MIROFISH_CONFIG_REVISION', '')}


def apply_selected_config(expected_revision=None):
    with _config_apply_lock:
        if health_snapshot()['busy']:
            raise ValueError('任务正在执行，请在任务结束后启用新预设。')
        from local_studio.config_store import ConfigStore
        store = ConfigStore(os.environ.get('MIROFISH_DATA_ROOT', os.environ['MIROFISH_STUDIO_ROOT']))
        # The HTTP route requires a supplied revision. Keep direct internal calls
        # compatible while still validating an atomic selection before mutation.
        expected_revision = expected_revision if expected_revision is not None else store.runtime_revision()
        selected = store.runtime_selection(expected_revision=expected_revision)
        model, zep = selected['model'], selected['zep']
        if not model.get('model'):
            raise ValueError('请先填写模型名称。')
        key = model.get('key')
        if not key and urlsplit(model['base_url']).hostname in {'localhost', '127.0.0.1', '::1'}:
            key = 'local-no-key'
        if not key or not zep.get('key'):
            raise ValueError('请先完善模型与 Zep 连接配置。')
        Config.LLM_API_KEY = key
        Config.LLM_BASE_URL = model['base_url']
        Config.LLM_MODEL_NAME = model['model']
        Config.ZEP_API_KEY = zep['key']
        os.environ.update({'LLM_API_KEY': key, 'LLM_BASE_URL': model['base_url'],
                           'LLM_MODEL_NAME': model['model'], 'ZEP_API_KEY': zep['key'],
                           'MIROFISH_MODEL_ID': model['id']})
        # Publish last and under the same lock read by health. A confirmed
        # revision always describes an entirely applied runtime snapshot.
        os.environ['MIROFISH_CONFIG_REVISION'] = selected['revision']
        return {'model_id': model['id'], 'runtime_revision': selected['revision'],
                'message': '已用于后续任务；已有采访保留原模型。'}
