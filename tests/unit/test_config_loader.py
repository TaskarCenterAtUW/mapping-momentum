"""Unit tests for mm.config.loader.

All tests are fully offline — no network calls, no real filesystem side
effects beyond temporary files created via tmp_path.

Test matrix:
  - valid v1.1 event config loads successfully (file and directory paths)
  - schema validation rejects missing required fields
  - non-slug-safe event.id is rejected
  - non-slug-safe activity.id is rejected
  - duplicate activity.id within an event is rejected
  - malformed event.date is rejected
  - non-UTC timestamp in time_window is rejected
  - malformed timestamp in time_window is rejected
  - time_window where start >= end is rejected
  - missing credential env var is rejected
  - v1.1: quest_definition_url required and non-empty
  - v1.1: quest_definition_retrieval_date must be UTC ISO 8601 if present
  - report optional object accepted
  - showcase_photos URL src accepted
  - showcase_photos relative src validated against event directory
  - _event_dir key present in returned config
  - missing event.json in directory raises FileNotFoundError
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

# A minimal valid v1.1 event config.  Individual tests mutate a deep copy.
_VALID_PROJECT_GROUP_ID = "832c0df9-1950-4c72-ac25-232c7752beb0"
_VALID_ENV_VAR = "MM_TDEI_API_KEY_PROD"
_VALID_QUEST_URL = (
    "https://raw.githubusercontent.com/TaskarCenterAtUW/asr-quests"
    "/refs/heads/main/quests/prod/SCLIO%20Vancouver/NDA%20Vancouver%20Walk%20Roll.json"
)


def _base_config() -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "type": "event",
        "id": "nda-vancouver",
        "name": "NDA Vancouver Walk/Roll",
        "date": "2026-01-20",
        "activities": [
            {
                "id": "walkabout",
                "type": "workspace",
                "label": "NDA Vancouver Walk/Roll",
                "project_group_id": _VALID_PROJECT_GROUP_ID,
                "workspace_id": 931,
                "environment": "prod",
                "quest_definition_url": _VALID_QUEST_URL,
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


def _write_dir_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    """Write config as JSON inside an event directory."""
    slug = config.get("id", "test-event")
    event_dir = tmp_path / slug
    event_dir.mkdir(parents=True, exist_ok=True)
    (event_dir / "event.json").write_text(json.dumps(config), encoding="utf-8")
    return event_dir


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


def test_schema_version_1_0_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["schema_version"] = "1.0"
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


# ---------------------------------------------------------------------------
# Directory-based loading
# ---------------------------------------------------------------------------


def test_load_from_directory(tmp_path: Path) -> None:
    event_dir = _write_dir_config(tmp_path, _base_config())
    loaded = load_event_config(event_dir)
    assert loaded["id"] == "nda-vancouver"
    assert loaded["activities"][0]["workspace_id"] == 931


def test_event_dir_in_returned_config_from_file(tmp_path: Path) -> None:
    p = _write_config(tmp_path, _base_config())
    loaded = load_event_config(p)

    assert "_event_dir" in loaded
    assert loaded["_event_dir"] == tmp_path


def test_event_dir_in_returned_config_from_directory(tmp_path: Path) -> None:
    event_dir = _write_dir_config(tmp_path, _base_config())
    loaded = load_event_config(event_dir)
    assert loaded["_event_dir"] == event_dir


def test_missing_event_json_in_directory_raises(tmp_path: Path) -> None:
    empty_dir = tmp_path / "no-json-here"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="event.json"):
        load_event_config(empty_dir)


# ---------------------------------------------------------------------------
# v1.1 — quest_definition_url
# ---------------------------------------------------------------------------


def test_v1_1_requires_quest_definition_url(tmp_path: Path) -> None:
    config = _base_config()
    del config["activities"][0]["quest_definition_url"]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="quest_definition_url"):
        load_event_config(p)


def test_v1_1_empty_quest_definition_url_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"][0]["quest_definition_url"] = ""
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="quest_definition_url"):
        load_event_config(p)


def test_v1_1_quest_definition_url_non_empty_accepted(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"][0]["quest_definition_url"] = "https://example.com/quest.json"
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert (
        loaded["activities"][0]["quest_definition_url"]
        == "https://example.com/quest.json"
    )


@pytest.mark.parametrize(
    "invalid_url",
    ["http://example.com/quest.json", "file:///tmp/quest.json", "not-a-url"],
)
def test_v1_1_quest_definition_url_must_be_https(
    tmp_path: Path, invalid_url: str
) -> None:
    config = _base_config()
    config["activities"][0]["quest_definition_url"] = invalid_url
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="must be an HTTPS URL"):
        load_event_config(p)


# ---------------------------------------------------------------------------
# v1.1 — quest_definition_retrieval_date
# ---------------------------------------------------------------------------


def test_quest_definition_retrieval_date_valid_utc(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"][0]["quest_definition_retrieval_date"] = "2026-06-26T14:32:00Z"
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert (
        loaded["activities"][0]["quest_definition_retrieval_date"]
        == "2026-06-26T14:32:00Z"
    )


def test_quest_definition_retrieval_date_non_utc_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["activities"][0]["quest_definition_retrieval_date"] = (
        "2026-06-26T14:32:00+05:00"
    )
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError):
        load_event_config(p)


def test_quest_definition_retrieval_date_absent_accepted(tmp_path: Path) -> None:
    config = _base_config()
    assert "quest_definition_retrieval_date" not in config["activities"][0]
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert "quest_definition_retrieval_date" not in loaded["activities"][0]


# ---------------------------------------------------------------------------
# report (optional)
# ---------------------------------------------------------------------------


def test_report_with_title_accepted(tmp_path: Path) -> None:
    config = _base_config()
    config["report"] = {"title": "My Custom Report Title"}
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert loaded["report"]["title"] == "My Custom Report Title"


def test_report_with_subtitle_accepted(tmp_path: Path) -> None:
    config = _base_config()
    config["report"] = {"title": "Title", "subtitle": "Custom subtitle"}
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert loaded["report"]["subtitle"] == "Custom subtitle"


def test_report_with_unknown_field_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["report"] = {"title": "Title", "unknown_field": "x"}
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_report_absent_accepted(tmp_path: Path) -> None:
    config = _base_config()
    assert "report" not in config
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert "report" not in loaded


# ---------------------------------------------------------------------------
# showcase_photos
# ---------------------------------------------------------------------------


def test_showcase_photos_url_src_accepted(tmp_path: Path) -> None:
    config = _base_config()
    config["showcase_photos"] = [
        {"src": "https://example.com/photo.jpg", "caption": "A photo"}
    ]
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert loaded["showcase_photos"][0]["src"] == "https://example.com/photo.jpg"


def test_showcase_photos_http_src_accepted(tmp_path: Path) -> None:
    config = _base_config()
    config["showcase_photos"] = [{"src": "http://example.com/photo.jpg"}]
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert len(loaded["showcase_photos"]) == 1


def test_showcase_photos_relative_src_existing_file_accepted(tmp_path: Path) -> None:
    event_dir = _write_dir_config(tmp_path, _base_config())
    showcase_dir = event_dir / "showcase"
    showcase_dir.mkdir()
    (showcase_dir / "001.jpg").write_bytes(b"fake-image")
    config = _base_config()
    config["showcase_photos"] = [{"src": "showcase/001.jpg", "caption": "Volunteers"}]
    (event_dir / "event.json").write_text(json.dumps(config), encoding="utf-8")
    loaded = load_event_config(event_dir)
    assert loaded["showcase_photos"][0]["src"] == "showcase/001.jpg"


def test_showcase_photos_relative_src_missing_file_raises(tmp_path: Path) -> None:
    event_dir = _write_dir_config(tmp_path, _base_config())
    config = _base_config()
    config["showcase_photos"] = [{"src": "showcase/missing.jpg"}]
    (event_dir / "event.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConfigError, match="does not exist"):
        load_event_config(event_dir)


def test_showcase_photos_empty_src_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["showcase_photos"] = [{"src": ""}]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="must not be empty"):
        load_event_config(p)


def test_showcase_photos_missing_src_raises(tmp_path: Path) -> None:
    config = _base_config()
    config["showcase_photos"] = [{"caption": "No src field"}]
    p = _write_config(tmp_path, config)
    with pytest.raises(ConfigError, match="Schema validation failed"):
        load_event_config(p)


def test_showcase_photos_absent_accepted(tmp_path: Path) -> None:
    config = _base_config()
    assert "showcase_photos" not in config
    p = _write_config(tmp_path, config)
    loaded = load_event_config(p)
    assert "showcase_photos" not in loaded
