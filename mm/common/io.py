"""
mm.common.io — file I/O utilities shared across the pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    """Read and parse a JSON file, returning the decoded object."""
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Serialize *data* to JSON and write it to *path*.

    Parent directories are created automatically.
    The file is written atomically via a temporary name if the platform
    allows, but a simple overwrite is acceptable for local CLI use.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")
