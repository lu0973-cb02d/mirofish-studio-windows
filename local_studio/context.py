"""What the route modules share, so each stays a small, separate file."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from flask import Flask


@dataclass
class Context:
    app: Flask
    root: Path
    data_root: Path
    store: Any
    engine: Any
    ok: Callable[..., Any]
    payload: Callable[[], dict]
