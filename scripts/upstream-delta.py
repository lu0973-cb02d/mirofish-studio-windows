"""List how this repository differs from the upstream MiroFish snapshot it is based on.

    git clone https://github.com/666ghj/MiroFish ../MiroFish-upstream
    git -C ../MiroFish-upstream checkout <commit from source_info.json>
    python scripts/upstream-delta.py ../MiroFish-upstream > docs/UPSTREAM_DELTA.md

Only the parts that came from upstream are compared (backend, frontend, locales
and the root manifests). Everything under local_studio/, desktop/, packaging/,
scripts/, tests/ and docs/ belongs to this derivative. Use the output to see
which upstream files carry local changes before merging a newer upstream commit.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPARED = ("backend", "frontend", "locales", "package.json", "Dockerfile", "docker-compose.yml")
SKIPPED_DIRS = {"node_modules", ".venv", "__pycache__", "dist", "uploads", ".git"}
SKIPPED_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".zip"}


def files_under(root: Path, names: tuple[str, ...]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for name in names:
        base = root / name
        if base.is_file():
            found[name] = base
        elif base.is_dir():
            for path in sorted(base.rglob("*")):
                relative = path.relative_to(root)
                if (path.is_file() and not set(relative.parts) & SKIPPED_DIRS
                        and path.suffix.lower() not in SKIPPED_SUFFIXES):
                    found[relative.as_posix()] = path
    return found


def changed_lines(old: Path, new: Path) -> int:
    try:
        before = old.read_text(encoding="utf-8").splitlines()
        after = new.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return -1 if old.read_bytes() != new.read_bytes() else 0
    return sum(1 for line in difflib.unified_diff(before, after, lineterm="", n=0)
               if line[:1] in "+-" and line[:3] not in {"+++", "---"})


def main() -> None:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        raise SystemExit(__doc__)
    upstream = Path(sys.argv[1]).resolve()
    info = json.loads((REPO / "source_info.json").read_text(encoding="utf-8-sig"))
    ours, theirs = files_under(REPO, COMPARED), files_under(upstream, COMPARED)

    modified = sorted(((changed_lines(theirs[p], ours[p]), p) for p in ours.keys() & theirs.keys()), reverse=True)
    modified = [(n, p) for n, p in modified if n != 0]
    added = sorted(ours.keys() - theirs.keys())
    removed = sorted(theirs.keys() - ours.keys())

    print("# 与上游 MiroFish 的差异\n")
    print(f"对比基准：{info.get('source')} 提交 `{info.get('commit')}`（见 `source_info.json`）。")
    print("本文件由 `scripts/upstream-delta.py` 生成，只比较来自上游的目录（backend、frontend、locales 与根目录清单）。"
          "`local_studio/`、`desktop/`、`packaging/`、`scripts/`、`tests/`、`docs/` 是本衍生版自有的内容。\n")
    print("合并新的上游提交前，先看「已修改」一节：这些文件同时有本地改动和上游改动的风险最高。\n")
    print(f"## 已修改的上游文件（{len(modified)}）\n")
    print("| 文件 | 变动行数（增+删） |\n| --- | ---: |")
    for lines, path in modified:
        print(f"| `{path}` | {'二进制/编码不同' if lines < 0 else lines} |")
    print(f"\n## 本衍生版新增的文件（{len(added)}）\n")
    for path in added:
        print(f"- `{path}`")
    print(f"\n## 上游有、本衍生版没有的文件（{len(removed)}）\n")
    for path in removed or ["（无）"]:
        print(f"- `{path}`" if path != "（无）" else path)


if __name__ == "__main__":
    main()
