"""Unit tests for mm.config.loader.

All tests are fully offline — no network calls, no real filesystem side
effects beyond temporary files created via tmp_path.

Test matrix:
  - valid v1 event config loads successfully
  - schema validation rejects missing required fields
  - non-slug-safe event.id is rejected
  - non-slug-safe activity.id is rejected
  - duplicate activity.id within an event is rejected
  - malformed event.date is rejected
  - non-UTC timestamp in time_window is rejected
  - malformed timestamp in time_window is rejected
  - time_window where start >= end is rejected
  - missing credential env var is rejected
  - file not found raises FileNotFoundError
  - file with invalid JSON raises json.JSONDecodeError
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mm.config.loader import ConfigError, load_event_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A minimal valid v1 event config.  Individual tests mutate a deep copy.
_VALID_PROJECT_GROUP_ID = "832c0df9-1950-4c72-ac25-232c7752beb0"
_VALID_ENV_VAR = "MM_TDEI_API_KEY_PROD"


def _base_config() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "type": "event",
        "id": "nda-vancouver",
        "name": "NDA Vancouver",
        "date": "2026-01-20",
        "activities": [
            {
                "id": "walkabout",
                "type": "workspace",
                "label": "NDA Vancouver Walk/Roll",
                "project_group_id": _VALID_PROJECT_GROUP_ID,
                "workspace_id": 931,
                "environment": "prod",
                "time_window": {
                    "start": "2026-01-20T18:00:00Z",
                    "end": "2026-01-21T04:00:00Z",
                },
            }
        ],
    }


def _write_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    """Write *config* as JSON to a temp file and return the path."""
    p = tmp_path / "event.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_credential_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the required TDEI credential env var for the base config."""
    monkeypatch.setenv(_VALID_ENV_VAR, "test-api-key")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_config_loads(tmp_path: Path) -> None:
    config = _base_config()
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert loaded["id"] == "nda-vancouver"
    assert len(loaded["activities"]) == 1
    assert loaded["activities"][0]["workspace_id"] == 931


def test_valid_config_environment_defaults_to_prod(tmp_path: Path) -> None:
    """Missing activity 'environment' is an error; the field is required."""
    config = _base_config()
    del config["activities"][0]["environment"]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_valid_config_without_label(tmp_path: Path) -> None:
    config = _base_config()
    del config["activities"][0]["label"]
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert "label" not in loaded["activities"][0]


# ---------------------------------------------------------------------------
# Schema validation — missing required top-level fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["schema_version", "type", "id", "name", "date", "activities"],
)
def test_missing_top_level_field_raises(tmp_path: Path, missing_field: str) -> None:
    config = _base_config()
    del config[missing_field]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_wrong_schema_version_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["schema_version"] = "2.0"
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_wrong_config_type_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["type"] = "project"
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_empty_activities_list_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"] = []
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


@pytest.mark.parametrize(
    "missing_field",
    ["id", "type", "project_group_id", "workspace_id", "environment", "time_window"],
)
def test_missing_workspace_activity_field_raises(
    tmp_path: Path, missing_field: str
) -> None:
    config = _base_config()
    del config["activities"][0][missing_field]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_workspace_id_must_be_integer(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"][0]["workspace_id"] = "931"  # string instead of int
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_unknown_environment_raises(tmp_path: Path) -> None:
    config = _base_config()
    # not a supported environment
    config["activities"][0]["environment"] = "uat"
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "-leading-hyphen",
        "trailing-hyphen-",
        "UPPERCASE",
        "has space",
        "has_underscore",
        "has.dot",
        "",
    ],
)
def test_bad_event_id_raises(tmp_path: Path, bad_id: str) -> None:
    config = _base_config()
    config["id"] = bad_id
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="not slug-safe"):
        load_event_config(p)


@pytest.mark.parametrize(
    "bad_id",
    [
        "-leading-hyphen",
        "trailing-hyphen-",
        "UPPERCASE",
        "has space",
        "has_underscore",
        "has.dot",
        "",
    ],
)
def test_bad_activity_id_raises(tmp_path: Path, bad_id: str) -> None:
    config = _base_config()
    config["activities"][0]["id"] = bad_id
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="not slug-safe"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# Duplicate activity IDs
# ---------------------------------------------------------------------------


def test_duplicate_activity_id_raises(tmp_path: Path) -> None:
    config = _base_config()
    second = dict(config["activities"][0])
    second["project_group_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    second["workspace_id"] = 999
    # same id as the first activity; autouse fixture already sets the prod key
    config["activities"].append(second)
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="duplicated"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_date",
    ["2024/10/15", "October 15 2024", "15-10-2024", "2024-13-01", "not-a-date"],
)
def test_bad_event_date_raises(tmp_path: Path, bad_date: str) -> None:
    config = _base_config()
    config["date"] = bad_date
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="YYYY-MM-DD|not a valid"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2024-10-15T14:00:00",  # no timezone suffix
        "2024-10-15T14:00:00+05:00",  # non-UTC offset
        "not-a-timestamp",
        "2024-10-15",  # date only, no time
    ],
)
def test_non_utc_timestamp_raises(tmp_path: Path, bad_ts: str) -> None:
    config = _base_config()
    config["activities"][0]["time_window"]["start"] = bad_ts
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError):
        load_event_config(p)


def test_start_equal_to_end_raises(tmp_path: Path) -> None:
    config = _base_config()
    tw = config["activities"][0]["time_window"]
    tw["end"] = tw["start"]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="start and end must differ"):
        load_event_config(p)


def test_start_after_end_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"][0]["time_window"]["start"] = "2026-01-01T22:00:00Z"
    config["activities"][0]["time_window"]["end"] = "2026-01-01T14:00:00Z"
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="start must be before end"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# Credential env var
# ---------------------------------------------------------------------------


def test_missing_credential_env_var_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_VALID_ENV_VAR, raising=False)
    config = _base_config()
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="environment variable"):
        load_event_config(p)


@pytest.mark.parametrize(
    "environment, expected_var",
    [
        ("prod", "MM_TDEI_API_KEY_PROD"),
        ("stage", "MM_TDEI_API_KEY_STAGE"),
        ("dev", "MM_TDEI_API_KEY_DEV"),
    ],
)
def test_credential_var_per_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: str, expected_var: str
) -> None:
    """Each environment maps to its own named credential variable."""
    # Clear the prod key set by the autouse fixture, then set only the one we need.
    monkeypatch.delenv("MM_TDEI_API_KEY_PROD", raising=False)
    monkeypatch.setenv(expected_var, "some-key")
    config = _base_config()
    config["activities"][0]["environment"] = environment
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert loaded["activities"][0]["environment"] == environment


def test_credential_var_missing_for_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Activity in 'stage' fails if MM_TDEI_API_KEY_STAGE is not set."""
    monkeypatch.delenv("MM_TDEI_API_KEY_STAGE", raising=False)
    config = _base_config()
    config["activities"][0]["environment"] = "stage"
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="MM_TDEI_API_KEY_STAGE"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# File-level errors
# ---------------------------------------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_event_config(tmp_path / "does-not-exist.json")


def test_invalid_json_raises_decode_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json}", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_event_config(p)
