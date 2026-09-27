from pathlib import Path
from types import SimpleNamespace

from local_studio.engine import EngineManager


def test_reused_pid_is_not_adopted(monkeypatch, tmp_path):
    engine = EngineManager(tmp_path, object())
    engine.pid, engine.created = 9876, 100
    monkeypatch.setattr('local_studio.engine.psutil.Process', lambda _: SimpleNamespace(create_time=lambda: 101))
    assert engine._owned_process() is None


def test_foreign_working_directory_is_not_owned(monkeypatch, tmp_path):
    engine = EngineManager(tmp_path, object())
    engine.pid, engine.created = 9876, 100
    process = SimpleNamespace(create_time=lambda: 100, cmdline=lambda: ['python', 'run.py'],
                              cwd=lambda: str(tmp_path / 'someone-else'))
    monkeypatch.setattr('local_studio.engine.psutil.Process', lambda _: process)
    assert engine._owned_process() is None


def test_health_from_another_instance_never_marks_ready(monkeypatch, tmp_path):
    engine = EngineManager(tmp_path, object())
    engine.instance = 'ours'
    monkeypatch.setattr(engine, '_owned_process', lambda: object())
    monkeypatch.setattr(engine, 'health', lambda: {'service': 'MiroFish Backend', 'studio_instance': 'other'})
    state = engine.status()
    assert state['state'] == 'error'
    assert not state['healthy']


def test_windows_venv_redirector_can_change_cwd(monkeypatch, tmp_path):
    engine = EngineManager(tmp_path, object())
    engine.pid, engine.created = 9876, 100
    process = SimpleNamespace(create_time=lambda: 100,
        cmdline=lambda: [str(tmp_path / 'backend/.venv/Scripts/python.exe'), str(tmp_path / 'backend/run.py')],
        cwd=lambda: str(tmp_path / 'temp'))
    monkeypatch.setattr('local_studio.engine.psutil.Process', lambda _: process)
    assert engine._owned_process() is process
