"""Unit tests for mm.quests (loader and capture).

All tests are fully offline — no network calls.  HTTP is mocked via
monkeypatch where needed.

Test matrix
-----------
build_lookups:
  - builds correct tag_to_title
  - builds correct tag_value_to_label
  - builds correct tag_to_category
  - TextEntry quests present in tag_to_title/tag_to_category but absent from
    tag_value_to_label
  - missing 'elements' key raises ValueError
  - quest with no quest_tag is silently skipped
  - empty quests list in an element is handled gracefully
  - empty elements list returns empty lookups

load_quest_definition:
  - loads from the sample fixture file
  - file not found raises FileNotFoundError

capture_quest_definition:
  - fetches the URL and writes valid JSON to dest
  - returns a UTC ISO 8601 timestamp string
  - invalid JSON response raises json.JSONDecodeError
  - dest parent directories are created if absent

stamp_retrieval_date:
  - updates the matching activity's quest_definition_retrieval_date
  - preserves all other fields unchanged
  - raises KeyError for an unknown activity_id
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mm.quests.loader import QuestDefinition, build_lookups, load_quest_definition
from mm.quests.capture import capture_quest_definition, stamp_retrieval_date

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / \
    "quest-definition-sample.json"

_SAMPLE_RAW: dict[str, Any] = {
    "version": "3.0.0",
    "elements": [
        {
            "element_type": "Bus Stops",
            "quests": [
                {
                    "quest_id": 101,
                    "quest_title": "Is there a marked pedestrian path to the stop?",
                    "quest_type": "ExclusiveChoice",
                    "quest_tag": "ext:bus_stop_marked_ped_path",
                    "quest_answer_choices": [
                        {"value": "yes", "choice_text": "Yes"},
                        {"value": "no", "choice_text": "No"},
                        {"value": "unclear", "choice_text": "Unclear"},
                    ],
                },
                {
                    "quest_id": 102,
                    "quest_title": "What is the surface condition?",
                    "quest_type": "ExclusiveChoice",
                    "quest_tag": "ext:bus_stop_surface_condition",
                    "quest_answer_choices": [
                        {"value": "good", "choice_text": "Good"},
                        {"value": "fair", "choice_text": "Fair"},
                        {"value": "poor", "choice_text": "Poor"},
                    ],
                },
            ],
        },
        {
            "element_type": "Sidewalks",
            "quests": [
                {
                    "quest_id": 201,
                    "quest_title": "Is the sidewalk continuous?",
                    "quest_type": "ExclusiveChoice",
                    "quest_tag": "ext:sidewalk_continuous",
                    "quest_answer_choices": [
                        {"value": "yes", "choice_text": "Yes"},
                        {"value": "no", "choice_text": "No"},
                    ],
                },
                {
                    "quest_id": 202,
                    "quest_title": "Describe the hazards",
                    "quest_type": "TextEntry",
                    "quest_tag": "ext:sidewalk_navigation_hazards_text",
                },
            ],
        },
    ],
}


def _base_event_config() -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "type": "event",
        "id": "nda-test",
        "name": "Test Event",
        "date": "2026-01-01",
        "activities": [
            {
                "id": "walkabout",
                "type": "workspace",
                "label": "Test Walk/Roll",
                "project_group_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "workspace_id": 1,
                "environment": "prod",
                "quest_definition_url": "https://example.com/quest.json",
                "time_window": {
                    "start": "2026-01-01T10:00:00Z",
                    "end": "2026-01-01T18:00:00Z",
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# build_lookups — tag_to_title
# ---------------------------------------------------------------------------


def test_build_lookups_tag_to_title_bus_stop() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert qd.tag_to_title["ext:bus_stop_marked_ped_path"] == (
        "Is there a marked pedestrian path to the stop?"
    )


def test_build_lookups_tag_to_title_sidewalk() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert qd.tag_to_title["ext:sidewalk_continuous"] == "Is the sidewalk continuous?"


def test_build_lookups_tag_to_title_text_entry_present() -> None:
    """TextEntry quests must appear in tag_to_title."""
    qd = build_lookups(_SAMPLE_RAW)
    assert "ext:sidewalk_navigation_hazards_text" in qd.tag_to_title
    assert qd.tag_to_title["ext:sidewalk_navigation_hazards_text"] == "Describe the hazards"


def test_build_lookups_all_tags_present() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    expected_tags = {
        "ext:bus_stop_marked_ped_path",
        "ext:bus_stop_surface_condition",
        "ext:sidewalk_continuous",
        "ext:sidewalk_navigation_hazards_text",
    }
    assert set(qd.tag_to_title.keys()) == expected_tags


# ---------------------------------------------------------------------------
# build_lookups — tag_value_to_label
# ---------------------------------------------------------------------------


def test_build_lookups_choices_yes_no_unclear() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    choices = qd.tag_value_to_label["ext:bus_stop_marked_ped_path"]
    assert choices == {"yes": "Yes", "no": "No", "unclear": "Unclear"}


def test_build_lookups_choices_good_fair_poor() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    choices = qd.tag_value_to_label["ext:bus_stop_surface_condition"]
    assert choices == {"good": "Good", "fair": "Fair", "poor": "Poor"}


def test_build_lookups_text_entry_absent_from_choices() -> None:
    """TextEntry quests must NOT appear in tag_value_to_label."""
    qd = build_lookups(_SAMPLE_RAW)
    assert "ext:sidewalk_navigation_hazards_text" not in qd.tag_value_to_label


def test_build_lookups_exclusive_choice_present_in_choices() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert "ext:sidewalk_continuous" in qd.tag_value_to_label


# ---------------------------------------------------------------------------
# build_lookups — tag_to_category
# ---------------------------------------------------------------------------


def test_build_lookups_category_bus_stops() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert qd.tag_to_category["ext:bus_stop_marked_ped_path"] == "Bus Stops"
    assert qd.tag_to_category["ext:bus_stop_surface_condition"] == "Bus Stops"


def test_build_lookups_category_sidewalks() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert qd.tag_to_category["ext:sidewalk_continuous"] == "Sidewalks"
    assert qd.tag_to_category["ext:sidewalk_navigation_hazards_text"] == "Sidewalks"


def test_build_lookups_text_entry_has_category() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert "ext:sidewalk_navigation_hazards_text" in qd.tag_to_category


# ---------------------------------------------------------------------------
# build_lookups — edge cases
# ---------------------------------------------------------------------------


def test_build_lookups_missing_elements_raises() -> None:
    with pytest.raises(ValueError, match="'elements'"):
        build_lookups({"version": "3.0.0"})


def test_build_lookups_empty_elements_returns_empty() -> None:
    qd = build_lookups({"version": "3.0.0", "elements": []})
    assert qd.tag_to_title == {}
    assert qd.tag_value_to_label == {}
    assert qd.tag_to_category == {}


def test_build_lookups_quest_missing_tag_is_skipped() -> None:
    raw: dict[str, Any] = {
        "elements": [
            {
                "element_type": "Sidewalks",
                "quests": [
                    {
                        "quest_id": 999,
                        "quest_title": "No tag quest",
                        "quest_type": "ExclusiveChoice",
                        # no quest_tag field
                        "quest_answer_choices": [{"value": "yes", "choice_text": "Yes"}],
                    }
                ],
            }
        ]
    }
    qd = build_lookups(raw)
    assert qd.tag_to_title == {}


def test_build_lookups_empty_quests_list_in_element() -> None:
    raw: dict[str, Any] = {
        "elements": [
            {"element_type": "Crossings", "quests": []},
        ]
    }
    qd = build_lookups(raw)
    assert qd.tag_to_title == {}


def test_build_lookups_returns_quest_definition_instance() -> None:
    qd = build_lookups(_SAMPLE_RAW)
    assert isinstance(qd, QuestDefinition)


# ---------------------------------------------------------------------------
# load_quest_definition — from the committed sample fixture
# ---------------------------------------------------------------------------


def test_load_quest_definition_from_fixture() -> None:
    qd = load_quest_definition(_FIXTURE_PATH)
    assert isinstance(qd, QuestDefinition)
    # The fixture has 13 quests across 3 element types (Sidewalks, Crossings,
    # Kerbs): 8 with answer choices and 5 without (TextEntry / Numeric).
    assert len(qd.tag_to_title) == 13
    # Spot-check one tag from each element type.
    assert "ext:surface" in qd.tag_to_title
    assert "crossing:markings" in qd.tag_to_title
    assert "kerb" in qd.tag_to_title
    # TextEntry and Numeric quests must also be present.
    assert "ext:surface:description" in qd.tag_to_title
    assert "width" in qd.tag_to_title
    assert "ext:crossing:description" in qd.tag_to_title
    assert "height" in qd.tag_to_title


def test_load_quest_definition_choices_from_fixture() -> None:
    qd = load_quest_definition(_FIXTURE_PATH)
    # ExclusiveChoice: ext:surface (Sidewalks)
    assert qd.tag_value_to_label["ext:surface"] == {
        "asphalt": "Asphalt",
        "concrete": "Concrete",
        "paving_stones": "Brick",
        "gravel": "Gravel",
        "other": "Other",
    }
    # ExclusiveChoice: kerb (Kerbs) — note label "Ramp" for value "lowered"
    assert qd.tag_value_to_label["kerb"] == {
        "raised": "Raised",
        "lowered": "Ramp",
        "flush": "Flush",
    }
    # MultipleChoice: ext:obstruction:type (Sidewalks)
    assert "bollard" in qd.tag_value_to_label["ext:obstruction:type"]
    assert qd.tag_value_to_label["ext:obstruction:type"]["pole"] == "Utility Pole"
    # TextEntry and Numeric quests must be absent from tag_value_to_label.
    assert "ext:surface:description" not in qd.tag_value_to_label
    assert "width" not in qd.tag_value_to_label
    assert "height" not in qd.tag_value_to_label
    assert "ext:crossing:description" not in qd.tag_value_to_label


def test_load_quest_definition_categories_from_fixture() -> None:
    qd = load_quest_definition(_FIXTURE_PATH)
    # One representative tag per element type.
    assert qd.tag_to_category["ext:surface"] == "Sidewalks"
    assert qd.tag_to_category["crossing:markings"] == "Crossings"
    assert qd.tag_to_category["kerb"] == "Kerbs"
    # TextEntry / Numeric quests inherit their element type's category.
    assert qd.tag_to_category["ext:surface:description"] == "Sidewalks"
    assert qd.tag_to_category["ext:crossing:description"] == "Crossings"
    assert qd.tag_to_category["height"] == "Kerbs"


def test_load_quest_definition_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        load_quest_definition(Path("/nonexistent/quest-definition.json"))


# ---------------------------------------------------------------------------
# capture_quest_definition
# ---------------------------------------------------------------------------


def test_capture_writes_valid_json_to_dest(tmp_path: Path) -> None:
    dest = tmp_path / "quest-definition.json"
    definition = {"version": "3.0.0", "elements": []}
    payload = json.dumps(definition).encode()

    with patch("mm.quests.capture.fetch_bytes", return_value=payload):
        capture_quest_definition("https://example.com/q.json", dest)

    assert dest.exists()
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["version"] == "3.0.0"


def test_capture_returns_utc_timestamp(tmp_path: Path) -> None:
    dest = tmp_path / "quest-definition.json"
    payload = json.dumps({"elements": []}).encode()

    with patch("mm.quests.capture.fetch_bytes", return_value=payload):
        ts = capture_quest_definition("https://example.com/q.json", dest)

    # Must match YYYY-MM-DDTHH:MM:SSZ
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)


def test_capture_invalid_json_raises(tmp_path: Path) -> None:
    dest = tmp_path / "quest-definition.json"

    with patch("mm.quests.capture.fetch_bytes", return_value=b"{not json}"):
        with pytest.raises(json.JSONDecodeError):
            capture_quest_definition("https://example.com/q.json", dest)


def test_capture_creates_parent_directories(tmp_path: Path) -> None:
    dest = tmp_path / "deep" / "nested" / "quest-definition.json"
    payload = json.dumps({"elements": []}).encode()

    with patch("mm.quests.capture.fetch_bytes", return_value=payload):
        capture_quest_definition("https://example.com/q.json", dest)

    assert dest.exists()


def test_capture_does_not_write_on_invalid_json(tmp_path: Path) -> None:
    """Dest file must not be created when the response is not valid JSON."""
    dest = tmp_path / "quest-definition.json"

    with patch("mm.quests.capture.fetch_bytes", return_value=b"not-json"):
        with pytest.raises(json.JSONDecodeError):
            capture_quest_definition("https://example.com/q.json", dest)

    assert not dest.exists()


# ---------------------------------------------------------------------------
# stamp_retrieval_date
# ---------------------------------------------------------------------------


def test_stamp_writes_retrieval_date(tmp_path: Path) -> None:
    event_json = tmp_path / "event.json"
    event_json.write_text(json.dumps(_base_event_config()), encoding="utf-8")

    stamp_retrieval_date(event_json, "walkabout", "2026-06-26T14:32:00Z")

    loaded = json.loads(event_json.read_text(encoding="utf-8"))
    assert loaded["activities"][0]["quest_definition_retrieval_date"] == (
        "2026-06-26T14:32:00Z"
    )


def test_stamp_preserves_other_fields(tmp_path: Path) -> None:
    event_json = tmp_path / "event.json"
    event_json.write_text(json.dumps(_base_event_config()), encoding="utf-8")

    stamp_retrieval_date(event_json, "walkabout", "2026-06-26T14:32:00Z")

    loaded = json.loads(event_json.read_text(encoding="utf-8"))
    activity = loaded["activities"][0]
    assert activity["workspace_id"] == 1
    assert activity["quest_definition_url"] == "https://example.com/quest.json"
    assert loaded["id"] == "nda-test"


def test_stamp_unknown_activity_raises(tmp_path: Path) -> None:
    event_json = tmp_path / "event.json"
    event_json.write_text(json.dumps(_base_event_config()), encoding="utf-8")

    with pytest.raises(KeyError, match="no-such-id"):
        stamp_retrieval_date(event_json, "no-such-id", "2026-06-26T14:32:00Z")


def test_stamp_overwrites_existing_retrieval_date(tmp_path: Path) -> None:
    config = _base_event_config()
    config["activities"][0]["quest_definition_retrieval_date"] = "2025-01-01T00:00:00Z"
    event_json = tmp_path / "event.json"
    event_json.write_text(json.dumps(config), encoding="utf-8")

    stamp_retrieval_date(event_json, "walkabout", "2026-06-26T14:32:00Z")

    loaded = json.loads(event_json.read_text(encoding="utf-8"))
    assert loaded["activities"][0]["quest_definition_retrieval_date"] == (
        "2026-06-26T14:32:00Z"
    )
