"""Build and sign a MiroFish core update bundle.

    CORE_SIGNING_KEY=<64 hex> python scripts/build-core-bundle.py --version 1.2.0 --out dist-core

The bundle holds the merged, tested backend, locales and built UI of this
checkout (``npm --prefix frontend run build`` must have run). It never contains
the Studio layer, the Python runtime or user data. After signing, the result is
installed into a scratch directory through the same code the application uses,
so a bundle that would be refused in the field fails here instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from local_studio import core_update, ed25519  # noqa: E402

SKIP_DIRS = {"__pycache__", "tests", ".venv", "venv", "uploads", "node_modules", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}
BACKEND_FILES = ("run.py", "pyproject.toml", "uv.lock", "requirements.txt")


def collect(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}

    def add_tree(base: Path) -> None:
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith(".env") for part in relative.parts):
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            files[relative.as_posix()] = path

    for name in BACKEND_FILES:
        if (root / "backend" / name).is_file():
            files[f"backend/{name}"] = root / "backend" / name
    for tree in ("backend/app", "backend/scripts", "locales"):
        if (root / tree).is_dir():
            add_tree(root / tree)
    dist = root / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("frontend/dist is missing; run `npm --prefix frontend run build` first.")
    add_tree(dist)
    if (root / "source_info.json").is_file():
        files["source_info.json"] = root / "source_info.json"
    return files


def load_seed(args: argparse.Namespace) -> bytes:
    text = (Path(args.key_file).read_text(encoding="utf-8") if args.key_file
            else os.environ.get("CORE_SIGNING_KEY", "")).strip()
    try:
        seed = bytes.fromhex(text)
    except ValueError:
        seed = b""
    if len(seed) != 32:
        raise SystemExit("A 64-hex-character Ed25519 seed is required "
                         "(CORE_SIGNING_KEY or --key-file). Unsigned bundles are never produced.")
    return seed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True, help="core version, e.g. 1.2.0")
    parser.add_argument("--out", default="dist-core")
    parser.add_argument("--root", default=str(REPO))
    parser.add_argument("--key-file")
    parser.add_argument("--notes", default="", help="short release notes shown in the application")
    parser.add_argument("--python", default="3.11", help="Python minor version the bundle requires")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    core_update.parse_version(args.version)
    seed = load_seed(args)
    public = ed25519.public_key(seed)
    files = collect(root)

    info = json.loads((root / "source_info.json").read_text(encoding="utf-8-sig")) if (root / "source_info.json").is_file() else {}
    lock = (root / "backend" / "uv.lock").read_text(encoding="utf-8")
    entries = []
    for relative, path in files.items():
        data = path.read_bytes()
        entries.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    built_at = datetime.fromtimestamp(int(os.environ.get("SOURCE_DATE_EPOCH", datetime.now().timestamp())), timezone.utc)
    manifest = {
        "format": core_update.BUNDLE_FORMAT,
        "core_version": args.version,
        "built_at": built_at.isoformat(),
        "upstream": {"repo": info.get("source", ""), "commit": info.get("commit", "")},
        "notes": args.notes,
        "requires": {"studio_api": [core_update.STUDIO_API_LEVEL, core_update.STUDIO_API_LEVEL],
                     "python": args.python, "deps_sha256": core_update.deps_fingerprint(lock)},
        "files": entries,
    }
    raw = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    signature = ed25519.sign(seed, raw).hex()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bundle = out / core_update.ASSET_TEMPLATE.format(version=args.version)
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        def put(name: str, data: bytes) -> None:
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))  # reproducible
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
        put(core_update.MANIFEST_NAME, raw)
        put(core_update.SIGNATURE_NAME, signature.encode("ascii"))
        for relative, path in files.items():
            put(core_update.PAYLOAD_PREFIX + relative, path.read_bytes())

    # Install it exactly as an application would; refuse to publish anything it would refuse.
    with tempfile.TemporaryDirectory() as scratch:
        probe_root = Path(scratch) / "app"
        (probe_root / "backend").mkdir(parents=True)
        (probe_root / "backend" / "uv.lock").write_text(lock, encoding="utf-8")
        (probe_root / "source_info.json").write_text(json.dumps({"core_version": "0.0.0"}), encoding="utf-8")
        store = core_update.CoreStore(Path(scratch) / "data", probe_root, public_key_hex=public.hex())
        installed = store.install(bundle)
        store.verify_installed(installed)

    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    print(f"{bundle}  {bundle.stat().st_size} bytes  sha256={digest}")
    print(f"files={len(entries)} version={args.version} signed-by={public.hex()}")


if __name__ == "__main__":
    main()
