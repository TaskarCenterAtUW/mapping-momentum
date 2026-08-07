"""
mm.common.io — file I/O utilities shared across the pipeline.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_SAFE_PATH_COMPONENT = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def read_json(path: str | Path) -> Any:
    """Read and parse a JSON file, returning the decoded object."""
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    """Serialize *data* to JSON and write it to *path*.

    Parent directories are created automatically.
    The destination is replaced atomically after the JSON has been fully
    written, preventing interrupted report runs from leaving truncated files.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, dest)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_text(path: str | Path, text: str) -> None:
    """Write UTF-8 text atomically, creating parent directories as needed."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, dest)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def require_safe_path_component(value: str, field_name: str) -> str:
    """Validate a slug used as one component of an output path."""
    if not _SAFE_PATH_COMPONENT.fullmatch(value):
        raise ValueError(
            f"{field_name} must contain only lowercase letters, digits, and hyphens"
        )
    return value
