"""Write-then-rename helpers so concurrent readers never see a partial file.

The UI polls state, progress and profile files while background threads rewrite
them. ``open(path, "w")`` truncates first, so a reader can observe an empty or
half-written JSON document and the request fails with a decode error.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# On Windows ``os.replace`` fails while another handle has the target open
# without share-delete access, which is how Python opens files for reading.
_REPLACE_ATTEMPTS = 40
_REPLACE_DELAY_SECONDS = 0.05


def write_json_atomic(path: str | os.PathLike[str], data: Any, *, indent: int | None = 2) -> None:
    """Replace ``path`` with the JSON encoding of ``data`` in one step."""

    target = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    # Dot-prefixed ``.tmp`` names are skipped by record backups.
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory,
        prefix=f".{os.path.basename(target)}.", suffix=".tmp", delete=False,
    )
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(handle.name, target)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_DELAY_SECONDS)
    finally:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
