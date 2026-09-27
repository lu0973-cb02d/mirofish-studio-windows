import json

import pytest

from app.services import simulation_runner as runner


def test_checkpoint_failure_preserves_last_complete_record(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(runner.SimulationRunner, '_run_states', {})
    state = runner.SimulationRunState(simulation_id='sim_atomic', current_round=2)
    runner.SimulationRunner._save_run_state(state)
    path = tmp_path / 'sim_atomic/run_state.json'
    previous = path.read_bytes()
    state.current_round = 3
    def interrupted(source, destination):
        assert json.loads(open(source, encoding='utf-8').read())['current_round'] == 3
        assert path.read_bytes() == previous
        raise OSError('simulated interruption')
    monkeypatch.setattr(runner.os, 'replace', interrupted)
    with pytest.raises(OSError):
        runner.SimulationRunner._save_run_state(state)
    assert path.read_bytes() == previous
    assert not list(path.parent.glob('.run-state-*.tmp'))


def test_checkpoint_is_readable_after_reopening(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.SimulationRunner, 'RUN_STATE_DIR', str(tmp_path))
    monkeypatch.setattr(runner.SimulationRunner, '_run_states', {})
    state = runner.SimulationRunState(simulation_id='sim_saved', runner_status=runner.RunnerStatus.COMPLETED,
        current_round=4, total_rounds=4, twitter_completed=True, reddit_completed=True)
    runner.SimulationRunner._save_run_state(state)
    runner.SimulationRunner._run_states.clear()
    restored = runner.SimulationRunner.get_run_state('sim_saved')
    assert restored.runner_status == runner.RunnerStatus.COMPLETED
    assert restored.twitter_completed and restored.reddit_completed
    assert restored.current_round == 4
