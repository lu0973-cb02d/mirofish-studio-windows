"""Local backup compatibility, recovery and automatic-retention checks."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import record_backup as backup
from local_studio.autobackup import AutoBackup


def bindings(graph="graph", identity="zep_a"):
    row = {"group": "key:" + identity, "key_id": identity, "graph_id": graph}
    return {"version": 1, "graphs": {graph: row}, "resources": {"episode:ep-" + graph: row}}


def prepare(root):
    records = root / "backend/uploads"
    records.mkdir(parents=True)
    (records / "project.json").write_text('{"title":"before"}', encoding="utf-8")
    studio = root / "studio_data"
    studio.mkdir()
    (studio / "zep_bindings.json").write_text(json.dumps(bindings()), encoding="utf-8")
    return records, studio


def legacy_archive(path, entries=None, **extra):
    entries = entries if entries is not None else {"project.json": b'{"title":"legacy"}'}
    manifest = {"format": backup.LEGACY_FORMAT, "kind": "manual", "file_count": len(entries),
                "entries": [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in entries.items()], **extra}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr("records/" + name, data)
        archive.writestr("manifest.json", json.dumps(manifest))
    return path


def rewrite_archive(path, target, change):
    with zipfile.ZipFile(path) as archive:
        values = {name: archive.read(name) for name in archive.namelist()}
    change(values)
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in values.items():
            archive.writestr(name, data)
    return target


def test_v2_contains_ownership_but_never_profiles_keys_or_cooldowns(tmp_path):
    records, studio = prepare(tmp_path)
    (studio / "config.json").write_text('{"key":"sensitive-key"}')
    (studio / "zep_health.json").write_text('{"cooldown_until":123}')
    value = bindings()
    value["api_key"] = "unexpected-top-key"
    value["graphs"]["graph"]["key"] = "unexpected-row-key"
    (studio / "zep_bindings.json").write_text(json.dumps(value))
    path = backup.create_backup(root=tmp_path)
    manifest = backup.verify_backup(path)
    assert manifest["format"] == backup.FORMAT
    assert manifest["file_count"] == 1
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {"manifest.json", "records/project.json", backup.BINDINGS_MEMBER}
        mapping = archive.read(backup.BINDINGS_MEMBER)
        assert b"unexpected" not in mapping
        assert json.loads(mapping) == bindings()


def test_restore_records_and_mapping_and_preserve_current_data(tmp_path):
    records, studio = prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    (records / "project.json").write_text("newer-data")
    newer = bindings("newer", "zep_b")
    (studio / "zep_bindings.json").write_text(json.dumps(newer))
    (studio / "config.json").write_text("untouched-config")
    (studio / "zep_health.json").write_text("untouched-health")
    manifest, previous = backup.restore_backup(path, root=tmp_path)
    assert json.loads((records / "project.json").read_text()) == {"title": "before"}
    assert json.loads((studio / "zep_bindings.json").read_text()) == bindings()
    assert (previous / "project.json").read_text() == "newer-data"
    protection = list((tmp_path / "record_backups").glob("before-restore-*.zep_bindings.json"))
    assert len(protection) == 1 and json.loads(protection[0].read_text()) == newer
    assert (studio / "config.json").read_text() == "untouched-config"
    assert (studio / "zep_health.json").read_text() == "untouched-health"
    assert manifest["zep_bindings_restored"] is True
    assert any("配置" in note for note in manifest["restore_notes"])


def test_legacy_v1_restores_and_retains_current_ownership(tmp_path):
    records, studio = prepare(tmp_path)
    original_mapping = (studio / "zep_bindings.json").read_bytes()
    path = legacy_archive(tmp_path / "legacy.zip")
    assert backup.verify_backup(path)["format"] == backup.LEGACY_FORMAT
    manifest, _ = backup.restore_backup(path, root=tmp_path)
    assert json.loads((records / "project.json").read_text())["title"] == "legacy"
    assert (studio / "zep_bindings.json").read_bytes() == original_mapping
    assert not manifest["zep_bindings_restored"]
    assert any("旧版" in note for note in manifest["restore_notes"])


def test_restored_mapping_reports_missing_profile_ids(tmp_path, monkeypatch):
    from local_studio import config_store
    prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    monkeypatch.setattr(config_store, "ConfigStore", lambda _: SimpleNamespace(public=lambda: {"zep": []}))
    manifest, _ = backup.restore_backup(path, root=tmp_path)
    assert manifest["missing_zep_profile_ids"] == ["zep_a"]
    assert any("1 个原 Zep" in note for note in manifest["restore_notes"])


def test_retained_profile_id_remains_usable(tmp_path, monkeypatch):
    from local_studio import config_store
    prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    monkeypatch.setattr(config_store, "ConfigStore", lambda _: SimpleNamespace(public=lambda: {"zep": [{"id": "zep_a"}]}))
    manifest, _ = backup.restore_backup(path, root=tmp_path)
    assert manifest["missing_zep_profile_ids"] == []
    assert any("标识可复用" in note for note in manifest["restore_notes"])


@pytest.mark.parametrize("relative", ["../escape", "/absolute", "a/../../escape", "C:/escape", "a\\escape", "a/./x", "a//x", "a/x.", "a/x ", "CON", "dir/AUX.txt", "LPT1.txt", "x\x00y"])
def test_unsafe_zip_paths_are_rejected_before_records_change(tmp_path, relative):
    records, studio = prepare(tmp_path)
    path = legacy_archive(tmp_path / "unsafe.zip", {relative: b"attack"})
    with pytest.raises((ValueError, KeyError)):
        backup.restore_backup(path, root=tmp_path)
    assert json.loads((records / "project.json").read_text())["title"] == "before"


def test_case_colliding_paths_are_rejected_on_all_platforms(tmp_path):
    path = legacy_archive(tmp_path / "bad.zip", {"same/A.json": b"a", "same/a.json": b"b"})
    with pytest.raises(ValueError):
        backup.verify_backup(path)


def test_duplicate_manifest_entries_are_rejected(tmp_path):
    path = legacy_archive(tmp_path / "original.zip")
    def duplicate(values):
        manifest = json.loads(values["manifest.json"])
        manifest["entries"] *= 2
        manifest["file_count"] = 2
        values["manifest.json"] = json.dumps(manifest)
    bad = rewrite_archive(path, tmp_path / "duplicate.zip", duplicate)
    with pytest.raises(ValueError, match="重复"):
        backup.verify_backup(bad)


def test_unknown_archive_member_cannot_restore_a_config(tmp_path):
    records, studio = prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    bad = rewrite_archive(path, tmp_path / "extra.zip", lambda values: values.update({"studio/config.json": b'{"key":"bad"}'}))
    with pytest.raises(ValueError):
        backup.restore_backup(bad, root=tmp_path)
    assert not (studio / "config.json").exists()


def test_mapping_destination_is_a_fixed_whitelist(tmp_path):
    prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    def alter(values):
        manifest = json.loads(values["manifest.json"])
        manifest["zep_bindings"]["path"] = "../../outside.json"
        values["manifest.json"] = json.dumps(manifest)
    bad = rewrite_archive(path, tmp_path / "bad.zip", alter)
    with pytest.raises(ValueError):
        backup.verify_backup(bad)


def test_tampered_record_fails_integrity_check(tmp_path):
    records, studio = prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    bad = rewrite_archive(path, tmp_path / "bad.zip", lambda values: values.update({"records/project.json": b"tampered"}))
    with pytest.raises(ValueError):
        backup.restore_backup(bad, root=tmp_path)
    assert json.loads((records / "project.json").read_text())["title"] == "before"


def test_secret_field_in_archive_mapping_is_rejected_even_with_valid_hash(tmp_path):
    prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    def alter(values):
        value = json.loads(values[backup.BINDINGS_MEMBER])
        value["key"] = "must-not-restore"
        content = json.dumps(value).encode()
        values[backup.BINDINGS_MEMBER] = content
        manifest = json.loads(values["manifest.json"])
        manifest["zep_bindings"].update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
        values["manifest.json"] = json.dumps(manifest)
    bad = rewrite_archive(path, tmp_path / "bad.zip", alter)
    with pytest.raises(ValueError, match="不允许"):
        backup.verify_backup(bad)


def test_failed_binding_swap_rolls_records_back(tmp_path, monkeypatch):
    records, studio = prepare(tmp_path)
    path = backup.create_backup(root=tmp_path)
    (records / "project.json").write_text("current")
    current_mapping = bindings("current", "zep_current")
    (studio / "zep_bindings.json").write_text(json.dumps(current_mapping))
    original_replace = backup.os.replace
    def fail_mapping(source, destination):
        if Path(destination) == studio / "zep_bindings.json":
            raise OSError("simulated swap failure")
        return original_replace(source, destination)
    monkeypatch.setattr(backup.os, "replace", fail_mapping)
    with pytest.raises(OSError):
        backup.restore_backup(path, root=tmp_path)
    assert (records / "project.json").read_text() == "current"
    assert json.loads((studio / "zep_bindings.json").read_text()) == current_mapping
    assert path.is_file()


def test_sqlite_wal_snapshot_is_valid_without_stale_wal_members(tmp_path):
    records, studio = prepare(tmp_path)
    database = records / "sim.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE item (name TEXT)")
        connection.execute("INSERT INTO item VALUES ('saved')")
        connection.commit()
        assert database.with_name("sim.db-wal").exists()
        path = backup.create_backup(root=tmp_path)
        with zipfile.ZipFile(path) as archive:
            assert "records/sim.db-wal" not in archive.namelist()
            assert "records/sim.db-shm" not in archive.namelist()
            extracted = tmp_path / "check.db"
            extracted.write_bytes(archive.read("records/sim.db"))
        with sqlite3.connect(extracted) as restored:
            assert restored.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert restored.execute("SELECT name FROM item").fetchall() == [("saved",)]
    finally:
        connection.close()


def test_fast_consecutive_backups_do_not_replace_each_other(tmp_path):
    prepare(tmp_path)
    names = [backup.create_backup(root=tmp_path) for _ in range(3)]
    assert len(set(names)) == 3 and all(path.is_file() for path in names)


def test_non_scaffold_hidden_record_is_preserved(tmp_path):
    records, _ = prepare(tmp_path)
    (records / ".record-state.json").write_text("saved state")
    path = backup.create_backup(root=tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert archive.read("records/.record-state.json") == b"saved state"


def test_auto_skips_empty_records_and_unchanged_records(tmp_path):
    records = tmp_path / "backend/uploads"
    records.mkdir(parents=True)
    (records / ".gitkeep").write_text("")
    auto = AutoBackup(tmp_path)
    assert auto.run_once()["outcome"] == "empty"
    (records / "project.json").write_text("first")
    assert auto.run_once()["outcome"] == "created"
    assert auto.run_once()["outcome"] == "unchanged"
    # A second controller also reads the same persistent fingerprint.
    assert AutoBackup(tmp_path).run_once()["outcome"] == "unchanged"
    (records / "project.json").write_text("second-longer")
    assert auto.run_once()["outcome"] == "created"
    assert len(backup.list_backups(root=tmp_path)) == 2


def test_auto_retains_20_auto_archives_and_all_manual_archives(tmp_path):
    records, studio = prepare(tmp_path)
    manual = backup.create_backup(root=tmp_path)
    pre_restore = backup.create_backup("pre-restore", root=tmp_path)
    auto = AutoBackup(tmp_path)
    for index in range(22):
        (records / "project.json").write_text("data-" + str(index) + "x" * index)
        assert auto.run_once()["outcome"] == "created"
    assert len(list((tmp_path / "record_backups").glob("records-auto-*.zip"))) == 20
    assert manual.exists() and pre_restore.exists()


def test_auto_and_manual_backups_share_mutual_exclusion(tmp_path):
    prepare(tmp_path)
    auto = AutoBackup(tmp_path)
    result = []
    with backup.backup_guard(root=tmp_path):
        worker = threading.Thread(target=lambda: result.append(auto.run_once()["outcome"]))
        worker.start()
        worker.join(timeout=2)
    assert not worker.is_alive() and result == ["busy"]
    assert not backup.list_backups(root=tmp_path)


def test_backup_mutex_also_excludes_a_second_process(tmp_path):
    prepare(tmp_path)
    script = ("import record_backup\n"
              "with record_backup.backup_guard(root=" + repr(str(tmp_path)) + ", blocking=False) as acquired:\n"
              "    print('acquired' if acquired else 'busy')\n")
    with backup.backup_guard(root=tmp_path):
        result = subprocess.run([sys.executable, "-c", script], cwd=Path(backup.__file__).parent,
                                text=True, capture_output=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == "busy"


def test_auto_error_is_safe_and_next_run_can_retry(tmp_path, monkeypatch):
    prepare(tmp_path)
    auto = AutoBackup(tmp_path)
    original = backup.create_backup
    monkeypatch.setattr(backup, "create_backup", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret payload")))
    status = auto.run_once()
    assert status["outcome"] == "error" and "secret" not in json.dumps(status)
    monkeypatch.setattr(backup, "create_backup", original)
    assert auto.run_once()["outcome"] == "created"


def test_auto_thread_starts_once_and_releases_on_stop(tmp_path):
    auto = AutoBackup(tmp_path, interval_seconds=900)
    auto.start()
    first = auto._thread
    auto.start()
    assert auto._thread is first
    assert auto.stop(timeout=3)
    assert not first.is_alive() and auto.status()["enabled"] is False
