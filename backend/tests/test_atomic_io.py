import json
import threading

import pytest

from app.utils.atomic_io import write_json_atomic


def test_writes_readable_json_and_leaves_no_temporary_files(tmp_path):
    target = tmp_path / "nested" / "state.json"

    write_json_atomic(target, {"名称": "推演", "round": 3})

    assert json.loads(target.read_text(encoding="utf-8")) == {"名称": "推演", "round": 3}
    assert "名称" in target.read_text(encoding="utf-8")  # not ASCII-escaped
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]


def test_a_failed_write_keeps_the_previous_document(tmp_path):
    target = tmp_path / "state.json"
    write_json_atomic(target, {"version": 1})

    with pytest.raises(TypeError):
        write_json_atomic(target, {"version": object()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_concurrent_readers_never_observe_a_partial_document(tmp_path):
    """The failure that surfaced as HTTP 500 when a poll met a rewrite."""
    target = tmp_path / "state.json"
    payload = {"rows": ["x" * 80] * 3000}
    write_json_atomic(target, payload)
    stop = threading.Event()
    errors = []

    def read():
        while not stop.is_set():
            try:
                assert json.loads(target.read_text(encoding="utf-8")) == payload
            except Exception as error:  # noqa: BLE001 - any failure is the bug
                errors.append(repr(error))
                return

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for _ in range(300):
            write_json_atomic(target, payload)
    finally:
        stop.set()
        reader.join()

    assert errors == []
