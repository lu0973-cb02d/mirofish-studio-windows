"""Scan the publishable source tree for credentials and local user data.

The audit intentionally reports paths and line numbers only; it never prints
the matched value. Build output and local runtime data are excluded because
they are not part of the source publication or release assets.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "dist-installers",
    "full-runtime",
    "stage",
    "runtime",
    "studio_data",
    "record_backups",
    "uploads",
    "__pycache__",
}
EXCLUDED_PREFIXES = (ROOT / "packaging" / "full-runtime",)
EXCLUDED_FILES = {".env", ".env.local", ".env.development", ".env.test", ".env.production"}
TEXT_SUFFIXES = {
    ".bat",
    ".cjs",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".pyi",
    ".pyw",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
    ".sh",
}
PLACEHOLDER_RE = re.compile(
    r"^(?:your[_-]|replace[_-]|change[_-]|example|sample|dummy|test|<|\$\{|xxx|none$|null$)",
    re.IGNORECASE,
)
PATTERNS = (
    ("openai", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._=-]{20,}")),
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"
            r"zep[_-]?api[_-]?key)\b\s*[:=]\s*['\"]([^'\"\r\n]{16,})['\"]"
        ),
    ),
    (
        "unquoted-credential-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"
            r"zep[_-]?api[_-]?key)\b\s*=\s*(?![\$'\"])(?=[A-Za-z0-9._-]*\d)"
            r"(?=[A-Za-z0-9._-]*[_\-.])[A-Za-z0-9._-]{24,}"
        ),
    ),
)


def excluded(path: Path) -> bool:
    if path.name in EXCLUDED_FILES or path.name.startswith(".env."):
        return True
    if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
        return True
    return any(path == prefix or prefix in path.parents for prefix in EXCLUDED_PREFIXES)


def text_for(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "LICENSE"}:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > 8 * 1024 * 1024 or b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")


def main() -> int:
    findings: list[dict[str, object]] = []
    test_fixture_findings: list[dict[str, object]] = []
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or excluded(path):
            continue
        text = text_for(path)
        if text is None:
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                if kind == "credential-assignment":
                    value = match.group(1).strip()
                    if PLACEHOLDER_RE.match(value):
                        continue
                item = {
                    "kind": kind,
                    "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "line": line_number,
                }
                if item["path"].startswith(("tests/", "backend/tests/")):
                    test_fixture_findings.append(item)
                else:
                    findings.append(item)
    result = {
        "scanned_text_files": scanned,
        "secret_findings": findings,
        "test_fixture_findings": test_fixture_findings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
