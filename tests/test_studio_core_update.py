"""Core update bundles: authenticity, hostile archives, compatibility, rollback."""

import json
import os
import zipfile

import pytest

from core_fixtures import (LOCK_TEXT, OTHER_SEED, App, Member, add_member, default_files, drop_member, find,
                           replace_data, symlink)
from local_studio import core_update
from local_studio.core_update import CoreUpdateError


@pytest.fixture
def app(tmp_path):
    return App(tmp_path)


def installed_dirs(app):
    return sorted(p.name for p in app.store.versions.iterdir()) if app.store.versions.exists() else []


# ---- the happy path ------------------------------------------------------------------

def test_install_activate_and_resolve_a_signed_bundle(app):
    assert app.store.resolve().source == "bundled"

    version = app.store.install(app.bundle("1.1.1"))
    assert version == "1.1.1"
    assert app.store.resolve().source == "bundled", "installing alone must not switch the core"

    selection = app.store.activate("1.1.1")
    assert (selection.source, selection.version, selection.upstream_commit) == ("downloaded", "1.1.1", "c0ffee")
    assert (selection.code_root / "backend" / "run.py").read_text() == "print('core 1.1.1')\n"
    assert selection.frontend_root == selection.code_root / "frontend" / "dist"
    assert app.store.status()["running"]["version"] == "1.1.1"
    assert app.store.status()["can_rollback"] is True


def test_the_bundled_core_is_used_when_nothing_is_active(app):
    selection = app.store.resolve()
    assert (selection.source, selection.version, selection.code_root) == ("bundled", "1.1.0", app.root)
    assert selection.frontend_root is None


def test_reinstalling_the_same_version_is_harmless(app):
    app.store.install(app.bundle("1.1.1"))
    assert app.store.install(app.bundle("1.1.1")) == "1.1.1"


def test_a_version_not_newer_than_the_bundled_core_is_refused(app):
    for version in ("1.1.0", "1.0.9", "0.9.0"):
        with pytest.raises(CoreUpdateError, match="无需安装"):
            app.store.install(app.bundle(version))
    assert installed_dirs(app) == []


# ---- authenticity -----------------------------------------------------------------------

def test_a_payload_altered_after_signing_is_refused(app):
    bundle = app.bundle("1.1.1", mutate=replace_data("core/backend/run.py", b"import os; os.system('evil')\n"))
    with pytest.raises(CoreUpdateError, match="校验失败|大小"):
        app.store.install(bundle)
    assert installed_dirs(app) == []


def test_a_manifest_altered_after_signing_is_refused(app):
    def edit(members):
        manifest = find(members, "MANIFEST.json")
        document = json.loads(manifest.data)
        document["core_version"] = "9.9.9"
        manifest.data = json.dumps(document, sort_keys=True).encode()
    with pytest.raises(CoreUpdateError, match="签名无效"):
        app.store.install(app.bundle("1.1.1", mutate=edit))


def test_a_bundle_signed_by_someone_else_is_refused(app):
    with pytest.raises(CoreUpdateError, match="签名无效"):
        app.store.install(app.bundle("1.1.1", seed=OTHER_SEED))


@pytest.mark.parametrize("signature", ["", "zz", "00" * 64, "00" * 10])
def test_missing_or_malformed_signatures_are_refused(app, signature):
    with pytest.raises(CoreUpdateError, match="签名"):
        app.store.install(app.bundle("1.1.1", signature=signature))


def test_a_bundle_without_manifest_or_signature_is_refused(app):
    with pytest.raises(CoreUpdateError, match="缺少清单或签名"):
        app.store.install(app.bundle("1.1.1", mutate=drop_member("MANIFEST.sig")))
    with pytest.raises(CoreUpdateError, match="缺少清单或签名"):
        app.store.install(app.bundle("1.1.2", mutate=drop_member("MANIFEST.json")))


def test_updates_are_disabled_until_a_public_key_is_built_in(tmp_path):
    keyless = App(tmp_path, public_hex="")
    assert keyless.store.enabled is False
    with pytest.raises(CoreUpdateError, match="公钥"):
        keyless.store.install(keyless.bundle("1.1.1"))
    with pytest.raises(CoreUpdateError, match="公钥"):
        keyless.store.activate("1.1.1")
    assert keyless.store.resolve().source == "bundled"


# ---- hostile archives -------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "backend/../../escape.py", "/etc/passwd", "backend\\evil.py", "C:/Windows/evil.py",
    "backend/con.py", "backend/trailing.", "backend/./x.py", "backend//x.py", "backend/a\x01b.py", "backend/",
])
def test_unsafe_manifest_paths_are_refused(app, path):
    bundle = app.bundle("1.1.1", files={path: b"x"})
    with pytest.raises(CoreUpdateError, match="不安全|不允许"):
        app.store.install(bundle)
    assert installed_dirs(app) == []
    assert not (app.tmp / "escape.py").exists()


@pytest.mark.parametrize("path", [
    "local_studio/server.py", "runtime/python.exe", "record_backup.py", "desktop/main.cjs", "../outside.py",
    "backendx/run.py", "frontend/src/App.vue",
])
def test_only_the_core_directories_can_be_updated(app, path):
    with pytest.raises(CoreUpdateError, match="不允许|不安全"):
        app.store.install(app.bundle("1.1.1", files={path: b"x"}))


def test_undeclared_members_are_refused(app):
    with pytest.raises(CoreUpdateError, match="不一致"):
        app.store.install(app.bundle("1.1.1", mutate=add_member(Member("core/backend/extra.py", b"x"))))
    with pytest.raises(CoreUpdateError, match="未声明"):
        app.store.install(app.bundle("1.1.2", mutate=add_member(Member("outside/payload.py", b"x"))))
    with pytest.raises(CoreUpdateError, match="不安全|未声明"):
        app.store.install(app.bundle("1.1.3", mutate=add_member(Member("core/../../evil.py", b"x"))))


def test_declared_members_that_are_missing_are_refused(app):
    with pytest.raises(CoreUpdateError, match="不一致"):
        app.store.install(app.bundle("1.1.1", mutate=drop_member("core/backend/app/__init__.py")))


def test_links_encryption_and_duplicates_are_refused(app):
    with pytest.raises(CoreUpdateError, match="链接"):
        app.store.install(app.bundle("1.1.1", mutate=add_member(symlink("core/backend/link"))))
    with pytest.raises(CoreUpdateError, match="加密"):
        app.store.install(app.bundle("1.1.2", mutate=add_member(Member("core/backend/enc.py", b"x", flags=1))))
    with pytest.raises(CoreUpdateError, match="重复"):
        app.store.install(app.bundle("1.1.3", mutate=add_member(Member("core/BACKEND/RUN.PY", b"x"))))
    with pytest.raises(CoreUpdateError, match="重复"):
        app.store.install(app.bundle("1.1.4", files={"backend/Case.py": b"1", "backend/case.py": b"2"}))


def test_a_manifest_size_that_lies_is_refused(app):
    def lie(members):
        manifest = find(members, "MANIFEST.json")
        document = json.loads(manifest.data)
        document["files"][0]["size"] += 1
        manifest.data = json.dumps(document, sort_keys=True).encode()
        # re-sign so only the size claim is wrong
        from local_studio import ed25519
        from core_fixtures import SEED
        find(members, "MANIFEST.sig").data = ed25519.sign(SEED, manifest.data).hex().encode()
    with pytest.raises(CoreUpdateError, match="大小|校验"):
        app.store.install(app.bundle("1.1.1", mutate=lie))
    assert installed_dirs(app) == []


def test_oversized_bundles_and_files_are_refused(app, monkeypatch):
    monkeypatch.setattr(core_update, "MAX_ZIP_BYTES", 10)
    with pytest.raises(CoreUpdateError, match="过大"):
        app.store.install(app.bundle("1.1.1"))
    monkeypatch.undo()
    monkeypatch.setattr(core_update, "MAX_FILE_BYTES", 5)
    with pytest.raises(CoreUpdateError, match="过大"):
        app.store.install(app.bundle("1.1.2"))


def test_not_a_zip_file_is_refused(app, tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(CoreUpdateError, match="无法打开"):
        app.store.install(junk)
    with pytest.raises(CoreUpdateError, match="无法打开"):
        app.store.install(tmp_path / "missing.zip")


def test_a_failed_extraction_leaves_nothing_behind(app, monkeypatch):
    real = core_update.CoreStore._extract

    def explode(self, archive, manifest, destination):
        real(self, archive, manifest, destination)
        raise OSError("disk full")

    monkeypatch.setattr(core_update.CoreStore, "_extract", explode)
    with pytest.raises(OSError):
        app.store.install(app.bundle("1.1.1"))
    assert installed_dirs(app) == []
    assert list(app.store.incoming.iterdir()) == []


def test_required_files_must_be_present(app):
    bundle = app.bundle("1.1.1", mutate=lambda m: None)
    files = default_files("1.1.1")
    del files["backend/run.py"]
    document = {"files": [{"path": p, "size": len(d), "sha256": __import__("hashlib").sha256(d).hexdigest()}
                          for p, d in sorted(files.items())]}
    gone = app.bundle("1.1.2", manifest=document, mutate=drop_member("core/backend/run.py"))
    with pytest.raises(CoreUpdateError, match="缺少必需文件"):
        app.store.install(gone)
    assert bundle.exists()


# ---- compatibility --------------------------------------------------------------------------

def test_a_bundle_for_another_studio_api_level_is_refused(app):
    with pytest.raises(CoreUpdateError, match="更新版本的工作台"):
        app.store.install(app.bundle("1.1.1", requires={"studio_api": [2, 3]}))
    with pytest.raises(CoreUpdateError, match="更新版本的工作台"):
        app.store.install(app.bundle("1.1.2", requires={"studio_api": "1"}))


def test_a_bundle_for_another_python_is_refused(app):
    with pytest.raises(CoreUpdateError, match="Python"):
        app.store.install(app.bundle("1.1.1", requires={"python": "3.9"}))


def test_a_bundle_needing_other_dependencies_is_refused(app):
    with pytest.raises(CoreUpdateError, match="依赖"):
        app.store.install(app.bundle("1.1.1", requires={"deps_sha256": "0" * 64}))
    with pytest.raises(CoreUpdateError, match="依赖"):
        app.store.install(app.bundle("1.1.2", requires={"deps_sha256": "not-a-hash"}))


@pytest.mark.parametrize("version", ["1.2", "v1.2.0", "1.2.0-beta", "01.2.0", "1.2.x", "", None, 120])
def test_malformed_versions_are_refused(app, version):
    with pytest.raises(CoreUpdateError):
        app.store.install(app.bundle("1.1.1", manifest={"core_version": version}))


def test_the_dependency_fingerprint_ignores_the_project_itself_and_order():
    first = core_update.deps_fingerprint(LOCK_TEXT)
    renamed = LOCK_TEXT.replace('version = "0.1.0"', 'version = "9.9.9"')
    assert core_update.deps_fingerprint(renamed) == first
    reordered = LOCK_TEXT.split("[[package]]")
    shuffled = "[[package]]".join([reordered[0], reordered[1], reordered[3], reordered[2]])
    assert core_update.deps_fingerprint(shuffled) == first
    assert core_update.deps_fingerprint(LOCK_TEXT.replace('"3.1.2"', '"3.1.3"')) != first
    with pytest.raises(CoreUpdateError):
        core_update.deps_fingerprint("this is = not [valid")
    with pytest.raises(CoreUpdateError):
        core_update.deps_fingerprint("version = 1\n")


# ---- verification at rest and fall-back ----------------------------------------------------------

def activated(app, version="1.1.1"):
    app.store.install(app.bundle(version))
    return app.store.activate(version)


@pytest.mark.parametrize("damage", ["edit", "delete", "add", "manifest", "signature", "symlink"])
def test_a_damaged_installed_core_is_ignored_in_favour_of_the_bundled_one(app, damage):
    selection = activated(app)
    root = selection.code_root
    if damage == "edit":
        (root / "backend" / "run.py").write_text("print('tampered')\n")
    elif damage == "delete":
        (root / "backend" / "run.py").unlink()
    elif damage == "add":
        (root / "backend" / "planted.py").write_text("x")
    elif damage == "manifest":
        (root / "MANIFEST.json").write_text("{}")
    elif damage == "signature":
        (root / "MANIFEST.sig").write_text("00" * 64)
    elif damage == "symlink":
        (root / "backend" / "link.py").symlink_to("/etc/passwd")
    app.store.invalidate()

    fallback = app.store.resolve()

    assert fallback.source == "bundled" and fallback.code_root == app.root
    assert "未通过校验" in fallback.notice


def test_a_newer_bundled_core_supersedes_an_older_installed_one(app):
    activated(app, "1.1.1")
    app.set_bundled("1.2.0")  # the user installed a newer full installer

    selection = app.store.resolve()

    assert selection.source == "bundled" and selection.version == "1.2.0"
    assert "不低于" in selection.notice
    with pytest.raises(CoreUpdateError, match="不高于内置核心"):
        app.store.activate("1.1.1")


def test_an_installed_core_is_dropped_when_the_runtime_dependencies_change(app):
    activated(app)
    (app.root / "backend" / "uv.lock").write_text(LOCK_TEXT.replace('"1.2.3"', '"2.0.0"'), encoding="utf-8")

    fallback = app.store.resolve()

    assert fallback.source == "bundled"
    assert "依赖" in fallback.notice


def test_a_corrupt_state_file_means_the_bundled_core(app):
    activated(app)
    app.store.state_file.write_text("{ not json")
    app.store.invalidate()
    assert app.store.resolve().source == "bundled"
    app.store.state_file.write_text(json.dumps({"active": "../../etc", "previous": [5, "x"]}))
    assert app.store.resolve().source == "bundled"


def test_activating_something_that_is_not_installed_fails(app):
    with pytest.raises(CoreUpdateError, match="缺失"):
        app.store.activate("1.1.1")
    with pytest.raises(CoreUpdateError):
        app.store.activate("../..")


# ---- rollback and pruning --------------------------------------------------------------------------

def test_rollback_walks_back_through_earlier_versions_to_the_bundled_core(app):
    for version in ("1.1.1", "1.1.2", "1.1.3"):
        app.store.install(app.bundle(version))
        app.store.activate(version)

    assert app.store.rollback().version == "1.1.2"
    assert app.store.rollback().version == "1.1.1"
    last = app.store.rollback()
    assert (last.source, last.version) == ("bundled", "1.1.0")
    with pytest.raises(CoreUpdateError, match="没有可回退"):
        app.store.rollback()


def test_rollback_skips_a_previous_version_that_no_longer_verifies(app):
    for version in ("1.1.1", "1.1.2"):
        app.store.install(app.bundle(version))
        app.store.activate(version)
    (app.store.versions / "1.1.1" / "backend" / "run.py").write_text("tampered")

    assert app.store.rollback().source == "bundled"


def test_prune_keeps_the_active_and_recent_versions_only(app):
    for version in ("1.1.1", "1.1.2", "1.1.3", "1.1.4", "1.1.5"):
        app.store.install(app.bundle(version))
        app.store.activate(version)

    removed = app.store.prune(keep=2)

    assert sorted(removed) == ["1.1.1", "1.1.2"]
    assert installed_dirs(app) == ["1.1.3", "1.1.4", "1.1.5"]
    assert app.store.resolve().version == "1.1.5"


def test_state_changes_are_published_atomically(app):
    activated(app)
    assert json.loads(app.store.state_file.read_text())["active"] == "1.1.1"
    assert [p.name for p in app.store.base.iterdir() if p.name.startswith(".")] == []
