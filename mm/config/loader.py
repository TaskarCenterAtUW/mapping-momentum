"""
mm.config.loader — load and validate Mapping Momentum JSON config files.

Validation is intentionally strict: every detected problem raises a
``ConfigError`` with a human-readable description.  The caller should
catch ``ConfigError`` and surface it to the user before doing any work.

*path* may be either an ``event.json`` file or an event directory; in
the latter case ``event.json`` is resolved automatically from the directory.
The returned dict is augmented with a ``_event_dir`` key (a
``pathlib.Path``) pointing to the event directory so callers can locate
sibling assets (``quest-definition.json``, ``showcase/`` photos, etc.)
without re-parsing the path.

Validation layers (applied in order):
  1. JSON Schema structural validation (jsonschema).
  2. Slug-safety of ``event.id`` and each ``activity.id``.
  3. YYYY-MM-DD format for ``event.date``.
  4. ISO 8601 UTC format for every ``time_window.start`` / ``.end``.
  5. Chronological order of each time window (start < end).
  6. Uniqueness of ``activity.id`` values within one event.
  7. Presence of the expected credential environment variable for every
     ``workspace`` activity (``MM_TDEI_API_KEY_PROD``, ``MM_TDEI_API_KEY_STAGE``,
     or ``MM_TDEI_API_KEY_DEV`` depending on the activity's ``environment``).
  8. ``quest_definition_url`` is present and non-empty on every
     ``workspace`` activity.
  9. ``quest_definition_retrieval_date``, when present, is a valid
     UTC ISO 8601 timestamp.
  10. ``showcase_photos`` relative ``src`` paths exist on disk (resolved
      against the event directory).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema

from mm.config.schema import (
    ENV_CREDENTIAL_VAR,
    EVENT_CONFIG_SCHEMA,
    SLUG_PATTERN,
)

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """Raised for any config validation failure."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Accepted UTC timestamp suffixes: 'Z' or explicit '+00:00'.
_UTC_SUFFIX_RE = re.compile(r"(Z|\+00:00)$")


def _parse_utc_timestamp(value: str, field_path: str) -> datetime:
    """Parse *value* as an ISO 8601 UTC timestamp and return a timezone-aware
    ``datetime``.  Raises ``ConfigError`` if the value is not a valid UTC
    timestamp."""
    if not _UTC_SUFFIX_RE.search(value):
        raise ConfigError(
            f"{field_path}: timestamp must be in UTC and end with 'Z' or '+00:00' "
            f"(got {value!r})"
        )
    # Normalise 'Z' → '+00:00' for Python < 3.11 fromisoformat compatibility
    normalised = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        raise ConfigError(f"{field_path}: {value!r} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ConfigError(f"{field_path}: timestamp must be in UTC (got {value!r})")
    return dt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_event_config(path: str | Path) -> dict[str, Any]:
    """Load and validate an event config from *path*.

    *path* may be:

    - A path to an ``event.json`` file (existing behaviour).
    - A path to an event directory; ``event.json`` is resolved inside it.

    Returns the validated config dict augmented with ``_event_dir``
    (a ``pathlib.Path`` to the event directory).  ``_event_dir`` is a
    loader-only key not present in the on-disk JSON; do not serialise it.

    Raises ``ConfigError`` on any validation failure.
    Raises ``FileNotFoundError`` if the path or resolved file does not exist.
    Raises ``json.JSONDecodeError`` if the file is not valid JSON.
    """
    path = Path(path)

    if path.is_dir():
        event_dir = path
        json_path = event_dir / "event.json"
        if not json_path.exists():
            raise FileNotFoundError(
                f"No event.json found in event directory: {event_dir}"
            )
    elif path.is_file():
        event_dir = path.parent
        json_path = path
    else:
        raise FileNotFoundError(f"Config path does not exist: {path}")

    with json_path.open(encoding="utf-8") as fh:
        try:
            config = json.load(fh)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"Config file {json_path} is not valid JSON: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc

    _validate_event_config(config, event_dir)
    config["_event_dir"] = event_dir
    return config


# ---------------------------------------------------------------------------
# Validation internals
# ---------------------------------------------------------------------------


def _validate_event_config(config: dict[str, Any], event_dir: Path) -> None:
    """Run all validation layers on a parsed event config dict."""

    # --- Layer 1: JSON Schema ---
    try:
        jsonschema.validate(config, EVENT_CONFIG_SCHEMA)
    except jsonschema.ValidationError as exc:
        # Surface the most relevant part of the jsonschema error message.
        path_str = " -> ".join(str(p) for p in exc.absolute_path) or "(root)"
        raise ConfigError(f"Schema validation failed at {path_str}: {exc.message}")

    # --- Layer 2: Slug safety ---
    event_id: str = config["id"]
    if not SLUG_PATTERN.match(event_id):
        raise ConfigError(
            f"event.id {event_id!r} is not slug-safe. "
            "Use only lowercase letters, digits, and hyphens; "
            "must not start or end with a hyphen."
        )

    # --- Layer 3: Event date format ---
    date_val: str = config["date"]
    if not _DATE_RE.match(date_val):
        raise ConfigError(f"event.date {date_val!r} must be in YYYY-MM-DD format")
    try:
        datetime.strptime(date_val, "%Y-%m-%d")
    except ValueError:
        raise ConfigError(f"event.date {date_val!r} is not a valid calendar date")

    # --- Layer 10: showcase_photos path validation ---
    if "showcase_photos" in config:
        _validate_showcase_photos(config["showcase_photos"], event_dir)

    # --- Layers 4-9: Per-activity validation ---
    seen_ids: set[str] = set()
    for idx, activity in enumerate(config.get("activities", [])):
        prefix = f"activities[{idx}]"

        # Layer 2 (continued): slug safety for activity.id
        act_id: str = activity["id"]
        if not SLUG_PATTERN.match(act_id):
            raise ConfigError(
                f"{prefix}.id {act_id!r} is not slug-safe. "
                "Use only lowercase letters, digits, and hyphens; "
                "must not start or end with a hyphen."
            )

        # Layer 6: uniqueness
        if act_id in seen_ids:
            raise ConfigError(
                f"{prefix}.id {act_id!r} is duplicated; "
                "activity IDs must be unique within an event"
            )
        seen_ids.add(act_id)

        # Layers 4, 5, 7, 8, 9: timestamp + credential validation
        if activity.get("type") == "workspace":
            _validate_workspace_activity(activity, prefix)


def _validate_workspace_activity(activity: dict[str, Any], prefix: str) -> None:
    """Validate workspace-specific fields for one activity."""
    tw = activity["time_window"]
    start = _parse_utc_timestamp(tw["start"], f"{prefix}.time_window.start")
    end = _parse_utc_timestamp(tw["end"], f"{prefix}.time_window.end")

    if start == end:
        raise ConfigError(
            f"{prefix}.time_window: start and end must differ "
            f"(got {tw['start']!r} for both)"
        )
    if start > end:
        raise ConfigError(
            f"{prefix}.time_window: start must be before end "
            f"(got start={tw['start']!r}, end={tw['end']!r})"
        )

    # Layer 7: credential env var presence
    environment: str = activity["environment"]
    env_var = ENV_CREDENTIAL_VAR[environment]
    if not os.environ.get(env_var):
        raise ConfigError(
            f"{prefix}: required environment variable {env_var!r} is not set. "
            f"Set it to the TDEI API key for the {environment!r} environment."
        )

    # Layer 8: quest_definition_url required
    url = activity.get("quest_definition_url", "")
    if not url:
        raise ConfigError(f"{prefix}.quest_definition_url is required")

    # Layer 9: quest_definition_retrieval_date must be UTC ISO 8601 if present
    retrieval_date = activity.get("quest_definition_retrieval_date")
    if retrieval_date is not None:
        _parse_utc_timestamp(
            retrieval_date, f"{prefix}.quest_definition_retrieval_date"
        )


def _validate_showcase_photos(photos: list, event_dir: Path) -> None:
    """Validate each showcase photo entry and check relative paths exist."""
    for i, photo in enumerate(photos):
        src: str = photo.get("src", "")
        if not src:
            raise ConfigError(f"showcase_photos[{i}].src must not be empty")
        if not (src.startswith("http://") or src.startswith("https://")):
            # Relative path — resolve against the event directory
            resolved = event_dir / src
            if not resolved.exists():
                raise ConfigError(
                    f"showcase_photos[{i}].src {src!r} does not exist "
                    f"(resolved to {resolved})"
                )
