"""Finding, downloading and building core bundles."""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from core_fixtures import LOCK_TEXT, PUBLIC_HEX, SEED, App
from local_studio import core_update
from local_studio.core_update import CoreUpdateError, Release, ReleaseSource

REPO = Path(__file__).resolve().parents[1]


def release_item(version, *, draft=False, prerelease=False, assets=True, tag=None, digest=None):
    name = f"mirofish-core-{version}.zip"
    item = {"tag_name": tag or f"core-v{version}", "draft": draft, "prerelease": prerelease,
            "body": f"notes for {version}", "published_at": "2026-10-01T00:00:00Z", "assets": []}
    if assets:
        asset = {"name": name, "size": 1234, "browser_download_url": f"https://github.com/o/r/releases/download/x/{name}"}
        if digest:
            asset["digest"] = f"sha256:{digest}"
        item["assets"].append(asset)
    return item


def source(handler):
    factory = lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)  # noqa: E731
    return ReleaseSource("https://api.github.com/repos/o/r/releases", client_factory=factory)


def listing(items):
    return source(lambda request: httpx.Response(200, json=items))


# ---- choosing a release ---------------------------------------------------------------

def test_the_highest_published_core_release_is_chosen():
    items = [
        release_item("1.1.1", draft=True), release_item("1.2.0", prerelease=True),
        release_item("1.9.9", tag="v1.9.9"),               # an installer release, not a core
        release_item("1.1.4", assets=False),               # no bundle attached
        release_item("9.9.9", tag="core-vABC"),            # not a version
        release_item("1.1.2"), release_item("1.1.3"), release_item("1.0.5"),
    ]
    release = listing(items).latest()
    assert (release.version, release.tag, release.size) == ("1.1.3", "core-v1.1.3", 1234)
    assert release.notes == "notes for 1.1.3"


@pytest.mark.parametrize("payload", [[], {"message": "not a list"}, [None, 5, "x", {"tag_name": 3}]])
def test_nothing_usable_means_no_release(payload):
    assert listing(payload).latest() is None


def test_the_release_digest_is_read_when_present():
    release = listing([release_item("1.1.1", digest="ab" * 32)]).latest()
    assert release.digest == "ab" * 32


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(500), "无法连接"),
    (httpx.Response(404), "无法连接"),
    (httpx.Response(403, text="API rate limit exceeded"), "过于频繁"),
    (httpx.Response(200, text="<html>captive portal</html>"), "无法识别"),
])
def test_server_problems_become_readable_errors(response, message):
    with pytest.raises(CoreUpdateError, match=message):
        source(lambda request: response).latest()


def test_a_network_failure_becomes_a_readable_error():
    def offline(request):
        raise httpx.ConnectError("no route")
    with pytest.raises(CoreUpdateError, match="无法连接更新服务器"):
        source(offline).latest()


@pytest.mark.parametrize("url", [
    "http://api.github.com/x", "https://evil.example/x", "https://github.com.evil.example/x",
    "https://evilgithub.com/x", "ftp://github.com/x", "https://githubusercontent.com.evil.io/x",
])
def test_only_https_github_hosts_are_trusted(url):
    assert core_update._trusted_url(url) is False


@pytest.mark.parametrize("url", [
    "https://github.com/o/r", "https://api.github.com/x", "https://objects.githubusercontent.com/x",
    "https://release-assets.githubusercontent.com/x", "http://127.0.0.1:8000/x", "http://localhost/x",
])
def test_github_and_its_download_hosts_are_trusted(url):
    assert core_update._trusted_url(url) is True


def test_an_untrusted_listing_address_is_never_contacted():
    def never(request):
        raise AssertionError("contacted")
    untrusted = ReleaseSource("https://evil.example/releases", client_factory=lambda: httpx.Client(
        transport=httpx.MockTransport(never)))
    with pytest.raises(CoreUpdateError, match="不受信任"):
        untrusted.latest()


# ---- downloading -------------------------------------------------------------------------

def release_for(url="https://github.com/o/r/releases/download/x/mirofish-core-1.1.1.zip", digest=""):
    return Release("1.1.1", "core-v1.1.1", "mirofish-core-1.1.1.zip", url, 5, digest)


def test_a_download_is_written_and_reported(tmp_path):
    seen = []
    target = source(lambda request: httpx.Response(200, content=b"hello")).download(
        release_for(), tmp_path / "x.zip", progress=lambda done, total: seen.append((done, total)))
    assert target.read_bytes() == b"hello" and seen[-1] == (5, 5)


def test_a_digest_mismatch_discards_the_download(tmp_path):
    with pytest.raises(CoreUpdateError, match="校验值不一致"):
        source(lambda request: httpx.Response(200, content=b"hello")).download(
            release_for(digest="00" * 32), tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()


def test_a_matching_digest_is_accepted(tmp_path):
    import hashlib
    good = hashlib.sha256(b"hello").hexdigest()
    assert source(lambda request: httpx.Response(200, content=b"hello")).download(
        release_for(digest=good), tmp_path / "x.zip").exists()


def test_an_oversized_download_is_stopped_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(core_update, "MAX_ZIP_BYTES", 3)
    with pytest.raises(CoreUpdateError, match="过大"):
        source(lambda request: httpx.Response(200, content=b"too long")).download(release_for(), tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()


def test_a_redirect_to_an_untrusted_host_is_refused(tmp_path):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://evil.example/payload.zip"})
        return httpx.Response(200, content=b"evil")
    with pytest.raises(CoreUpdateError, match="重定向"):
        source(handler).download(release_for(), tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()


def test_a_redirect_to_the_github_cdn_is_followed(tmp_path):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://objects.githubusercontent.com/p.zip"})
        return httpx.Response(200, content=b"cdn")
    assert source(handler).download(release_for(), tmp_path / "x.zip").read_bytes() == b"cdn"


def test_an_untrusted_asset_address_is_never_contacted(tmp_path):
    def never(request):
        raise AssertionError("contacted")
    with pytest.raises(CoreUpdateError, match="不受信任"):
        source(never).download(release_for("https://evil.example/a.zip"), tmp_path / "x.zip")


def test_a_failed_download_leaves_no_file(tmp_path):
    with pytest.raises(CoreUpdateError, match="下载更新包失败"):
        source(lambda request: httpx.Response(503)).download(release_for(), tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()


# ---- the whole check -> download -> install chain ------------------------------------------

def serve_bundle(app, version="1.1.1"):
    data = app.bundle(version).read_bytes()
    items = [release_item(version)]
    def handler(request):
        return httpx.Response(200, json=items) if "releases" in request.url.path and "download" not in request.url.path \
            else httpx.Response(200, content=data)
    return source(handler)


def test_check_reports_availability_and_installability(tmp_path):
    app = App(tmp_path)
    result, release = core_update.check_for_update(app.store, serve_bundle(app))
    assert result["available"] and result["latest"] == "1.1.1" and result["can_install"] is True
    assert release.version == "1.1.1"

    keyless = App(tmp_path / "k", public_hex="")
    result, _ = core_update.check_for_update(keyless.store, serve_bundle(keyless))
    assert result["available"] and result["can_install"] is False


def test_check_reports_when_up_to_date(tmp_path):
    app = App(tmp_path)
    for items in ([], [release_item("1.1.0")], [release_item("1.0.0")]):
        result, release = core_update.check_for_update(app.store, listing(items))
        assert result["available"] is False and release is None


def test_download_and_install_stages_the_signed_bundle(tmp_path):
    app = App(tmp_path)
    _, release = core_update.check_for_update(app.store, serve_bundle(app))
    assert core_update.download_and_install(app.store, serve_bundle(app), release) == "1.1.1"
    assert app.store.installed_versions() == ["1.1.1"]
    assert list(app.store.incoming.iterdir()) == []


def test_a_bundle_that_is_not_the_advertised_release_is_rejected(tmp_path):
    app = App(tmp_path)
    data = app.bundle("1.1.5").read_bytes()  # the page advertises 1.1.1 but serves 1.1.5
    release = release_for()
    with pytest.raises(CoreUpdateError, match="不一致"):
        core_update.download_and_install(app.store, source(lambda request: httpx.Response(200, content=data)), release)


# ---- the maintainer's build script ----------------------------------------------------------

def make_repo(tmp_path):
    repo = tmp_path / "repo"
    files = {
        "backend/run.py": "print('x')\n", "backend/uv.lock": LOCK_TEXT, "backend/pyproject.toml": "[project]\n",
        "backend/app/__init__.py": "", "backend/app/service.py": "VALUE = 1\n",
        "backend/app/__pycache__/service.cpython-311.pyc": "junk", "backend/scripts/run_sim.py": "pass\n",
        "backend/tests/test_secret.py": "KEY='shh'\n", "backend/.venv/lib/site.py": "junk",
        "backend/uploads/projects/p/project.json": "{}", "backend/app/.env.local": "SECRET=1",
        "backend/app/debug.log": "log", "locales/languages.json": "{}", "locales/en.json": "{}",
        "frontend/dist/index.html": "<html>ui</html>", "frontend/dist/assets/app.js": "1",
        "frontend/src/App.vue": "source, not shipped", "local_studio/server.py": "studio, not shipped",
        "source_info.json": json.dumps({"source": "https://example.invalid/up", "commit": "abc123", "core_version": "1.1.0"}),
    }
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return repo


def run_builder(repo, out, *args, seed=SEED.hex(), epoch="1700000000"):
    env = {**os.environ, "SOURCE_DATE_EPOCH": epoch}
    env.pop("CORE_SIGNING_KEY", None)
    if seed:
        env["CORE_SIGNING_KEY"] = seed
    return subprocess.run([sys.executable, str(REPO / "scripts/build-core-bundle.py"), "--root", str(repo),
                           "--out", str(out), *args], capture_output=True, text=True, env=env)


def test_the_builder_signs_only_core_files_and_the_result_installs(tmp_path):
    repo = make_repo(tmp_path)
    done = run_builder(repo, tmp_path / "out", "--version", "1.1.1")
    assert done.returncode == 0, done.stderr
    bundle = tmp_path / "out" / "mirofish-core-1.1.1.zip"

    import zipfile
    names = sorted(zipfile.ZipFile(bundle).namelist())
    shipped = {n for n in names if n.startswith("core/")}
    assert "core/backend/app/service.py" in shipped and "core/frontend/dist/assets/app.js" in shipped
    assert not [n for n in shipped if any(bad in n for bad in
                ("tests", ".venv", "__pycache__", "uploads", ".env", ".log", "local_studio", "src/App.vue"))]

    app = App(tmp_path / "field")
    assert app.store.install(bundle) == "1.1.1"
    selection = app.store.activate("1.1.1")
    assert (selection.code_root / "backend" / "app" / "service.py").read_text() == "VALUE = 1\n"
    assert selection.upstream_commit == "abc123"


def test_the_builder_never_produces_an_unsigned_bundle(tmp_path):
    repo = make_repo(tmp_path)
    for seed in ("", "not-hex", "ab" * 10):
        done = run_builder(repo, tmp_path / "out", "--version", "1.1.1", seed=seed)
        assert done.returncode != 0 and "Unsigned bundles are never produced" in (done.stderr + done.stdout)
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*.zip"))


def test_the_builder_needs_a_built_interface_and_a_valid_version(tmp_path):
    repo = make_repo(tmp_path)
    assert run_builder(repo, tmp_path / "out", "--version", "1.1").returncode != 0
    (repo / "frontend/dist/index.html").unlink()
    done = run_builder(repo, tmp_path / "out", "--version", "1.1.1")
    assert done.returncode != 0 and "frontend/dist is missing" in (done.stderr + done.stdout)


def test_builds_are_reproducible(tmp_path):
    repo = make_repo(tmp_path)
    run_builder(repo, tmp_path / "a", "--version", "1.1.1")
    run_builder(repo, tmp_path / "b", "--version", "1.1.1")
    assert (tmp_path / "a/mirofish-core-1.1.1.zip").read_bytes() == (tmp_path / "b/mirofish-core-1.1.1.zip").read_bytes()
