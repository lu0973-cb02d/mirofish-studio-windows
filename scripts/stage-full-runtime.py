"""Stage a self-contained Windows runtime for the MiroFish full installer.

The staged source contains code and the built UI, while user data and secrets
are deliberately left outside.  The Python runtime is copied from the local
uv-managed CPython installation and receives the current virtualenv's
site-packages, so the resulting installer does not need Python or pip on the
target machine.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging" / "full-runtime"
SOURCE_OUT = OUT / "mirofish"
RUNTIME_OUT = OUT / "runtime"
VENV = ROOT / "backend" / ".venv"

EXCLUDED_DIRS = {
    ".git", ".github", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", "uploads", "logs", "studio_data",
    "record_backups", "dist-installers", "packaging", "full-runtime",
    "tests",
}
EXCLUDED_FILES = {
    ".env", ".env.local", ".env.development", ".env.test", ".env.production",
    "install_log.txt", "SHA256SUMS.txt", "_regen_step4.ps1",
    "重新生成第四步报告.bat", "test_localsystem.txt",
}
EXCLUDED_SUFFIXES = {".log", ".zip", ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo"}


def source_ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    current = Path(directory)
    for name in names:
        path = current / name
        if path.is_dir() and name in EXCLUDED_DIRS:
            ignored.add(name)
            continue
        lowered = name.lower()
        if name in EXCLUDED_FILES or lowered.startswith(".env."):
            ignored.add(name)
        elif path.is_file() and path.suffix.lower() in EXCLUDED_SUFFIXES:
            ignored.add(name)
    return ignored


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_python_from_cfg() -> Path:
    cfg = VENV / "pyvenv.cfg"
    if not cfg.is_file():
        raise SystemExit(f"缺少虚拟环境描述文件: {cfg}")
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith("home ="):
            candidate = Path(line.split("=", 1)[1].strip())
            if candidate.is_dir() and (candidate / "python.exe").is_file():
                return candidate
    raise SystemExit("无法从 backend/.venv/pyvenv.cfg 定位 Python 运行时。")


def copy_source() -> None:
    if not (ROOT / "local_studio" / "server.py").is_file():
        raise SystemExit("当前目录不是 MiroFish 根目录。")
    if SOURCE_OUT.exists():
        shutil.rmtree(SOURCE_OUT)
    shutil.copytree(ROOT, SOURCE_OUT, ignore=source_ignore)


def copy_runtime() -> None:
    base = base_python_from_cfg()
    if RUNTIME_OUT.exists():
        shutil.rmtree(RUNTIME_OUT)
    # Copy the base interpreter and its standard library first.  It normally
    # has an empty site-packages directory; overlaying the venv packages below
    # keeps the runtime layout native to CPython on Windows.
    shutil.copytree(base, RUNTIME_OUT, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    target_site = RUNTIME_OUT / "Lib" / "site-packages"
    source_site = VENV / "Lib" / "site-packages"
    if not source_site.is_dir():
        raise SystemExit(f"缺少依赖目录: {source_site}")
    if target_site.exists():
        shutil.rmtree(target_site)
    shutil.copytree(source_site, target_site, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))


def write_manifest() -> None:
    files = []
    for path in OUT.rglob("*"):
        if path.is_file():
            files.append({
                "path": path.relative_to(OUT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
    manifest = {
        "format": 1,
        "source": "local MiroFish checkout",
        "python": str(base_python_from_cfg()),
        "file_count": len(files),
        "files": files,
        "excluded": sorted(EXCLUDED_DIRS | EXCLUDED_FILES),
        "excluded_suffixes": sorted(EXCLUDED_SUFFIXES),
        "contains_user_data": False,
        "contains_api_keys": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    copy_source()
    copy_runtime()
    write_manifest()
    total = sum(item["bytes"] for item in json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["files"])
    print(f"staged {len(list(OUT.rglob('*')))} entries, {total / 1024 / 1024:.1f} MiB")
    print(f"output: {OUT}")


if __name__ == "__main__":
    main()
