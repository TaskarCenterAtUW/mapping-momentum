"""Tests for the per-version quest answer CSV output."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from mm.outputs.quest_answer_log import (
    QUEST_ANSWER_LOG_FILENAME,
    build_quest_answer_log_rows,
    write_quest_answer_log,
)
from mm.quests.loader import QuestDefinition
from mm.sources.base import Version


def _version(
    action: str,
    user: str,
    timestamp: str,
    changeset: int,
    tags: dict[str, str],
) -> Version:
    """Create a version fixture with the fields used by the output."""
    return Version(
        action=action,
        user=user,
        timestamp=timestamp,
        changeset=changeset,
        tags=tags,
        readable={},
        photos=[],
    )


def _quest_definition() -> QuestDefinition:
    """Return a definition with choice and free-text questions."""
    return QuestDefinition(
        tag_to_title={
            "ext:surface": "What is the surface?",
            "ext:hazard": "Describe the hazard",
        },
        tag_value_to_label={
            "ext:surface": {
                "asphalt": "Asphalt",
                "concrete": "Concrete",
            }
        },
        tag_to_category={
            "ext:surface": "Sidewalks",
            "ext:hazard": "Sidewalks",
        },
    )


def test_build_quest_answer_log_rows_includes_changes_and_metadata() -> None:
    """Log choice and text edits, but omit unchanged and non-quest tags."""
    histories = {
        ("node", 9): [
            _version(
                "create",
                "alice",
                "2026-01-20T19:00:00Z",
                100,
                {
                    "ext:surface": "asphalt",
                    "ext:hazard": "Cracked curb",
                    "name": "Corner",
                },
            ),
            _version(
                "modify",
                "bob",
                "2026-01-20T20:00:00Z",
                101,
                {
                    "ext:surface": "concrete",
                    "ext:hazard": "Raised edge, needs\nreview",
                    "name": "Updated corner",
                },
            ),
            _version(
                "modify",
                "bob",
                "2026-01-20T21:00:00Z",
                102,
                {
                    "ext:surface": "concrete",
                    "ext:hazard": "Raised edge, needs\nreview",
                    "name": "Renamed corner",
                },
            ),
        ]
    }

    rows = build_quest_answer_log_rows(
        histories,
        _quest_definition(),
        event_id="sample-event",
        event_name="Sample Event",
        activity_id="walkabout",
        activity_label="Walkabout",
        workspace_id=931,
    )

    assert len(rows) == 4
    assert rows[0] == {
        "event_id": "sample-event",
        "event_name": "Sample Event",
        "activity_id": "walkabout",
        "activity_label": "Walkabout",
        "workspace_id": 931,
        "submitted_by": "alice",
        "submitted_at": "2026-01-20T19:00:00Z",
        "changeset_id": 100,
        "action": "create",
        "element_type": "node",
        "element_id": 9,
        "category": "Sidewalks",
        "question_tag": "ext:hazard",
        "question": "Describe the hazard",
        "previous_answer": "",
        "previous_answer_value_json": "null",
        "answer": "Cracked curb",
        "answer_value_json": json.dumps("Cracked curb"),
    }
    surface_change = next(
        row
        for row in rows
        if row["submitted_at"] == "2026-01-20T20:00:00Z"
        and row["question_tag"] == "ext:surface"
    )
    assert surface_change["submitted_by"] == "bob"
    assert surface_change["previous_answer"] == "Asphalt"
    assert surface_change["previous_answer_value_json"] == json.dumps("asphalt")
    assert surface_change["answer"] == "Concrete"
    assert surface_change["answer_value_json"] == json.dumps("concrete")


def test_build_quest_answer_log_rows_records_cleared_answers() -> None:
    """Keep the former answer when a quest tag is removed."""
    histories = {
        ("way", 12): [
            _version(
                "create",
                "alice",
                "2026-01-20T19:00:00Z",
                100,
                {"ext:surface": "asphalt"},
            ),
            _version(
                "delete",
                "bob",
                "2026-01-20T20:00:00Z",
                101,
                {},
            ),
        ]
    }

    rows = build_quest_answer_log_rows(
        histories,
        _quest_definition(),
        event_id="sample-event",
        event_name="Sample Event",
        activity_id="walkabout",
        activity_label="Walkabout",
        workspace_id=931,
    )

    deleted_answer = rows[-1]
    assert deleted_answer["action"] == "delete"
    assert deleted_answer["previous_answer"] == "Asphalt"
    assert deleted_answer["previous_answer_value_json"] == json.dumps("asphalt")
    assert deleted_answer["answer"] == ""
    assert deleted_answer["answer_value_json"] == "null"


def test_write_quest_answer_log_creates_csv_with_quoted_text(
    tmp_path: Path,
) -> None:
    """Write a valid CSV that preserves commas and embedded newlines."""
    rows = build_quest_answer_log_rows(
        {
            ("node", 9): [
                _version(
                    "create",
                    "alice",
                    "2026-01-20T19:00:00Z",
                    100,
                    {"ext:hazard": "Crack, with\nmultiple lines"},
                )
            ]
        },
        _quest_definition(),
        event_id="sample-event",
        event_name="Sample Event",
        activity_id="walkabout",
        activity_label="Walkabout",
        workspace_id=931,
    )

    destination = write_quest_answer_log(
        rows,
        tmp_path,
        "sample-event",
        "walkabout",
    )

    assert destination.name == QUEST_ANSWER_LOG_FILENAME
    with destination.open(encoding="utf-8", newline="") as stream:
        saved_rows = list(csv.DictReader(stream))
    assert saved_rows[0]["answer"] == "Crack, with\nmultiple lines"
    assert saved_rows[0]["submitted_by"] == "alice"


def test_write_quest_answer_log_neutralizes_formula_cells(
    tmp_path: Path,
) -> None:
    """Keep spreadsheet formulas inert while retaining the original answer."""
    answer = '=HYPERLINK("https://example.invalid", "open")'
    rows = build_quest_answer_log_rows(
        {
            ("node", 9): [
                _version(
                    "create",
                    "alice",
                    "2026-01-20T19:00:00Z",
                    100,
                    {"ext:hazard": answer},
                )
            ]
        },
        _quest_definition(),
        event_id="sample-event",
        event_name="Sample Event",
        activity_id="walkabout",
        activity_label="Walkabout",
        workspace_id=931,
    )

    destination = write_quest_answer_log(
        rows,
        tmp_path,
        "sample-event",
        "walkabout",
    )

    with destination.open(encoding="utf-8", newline="") as stream:
        saved_row = next(csv.DictReader(stream))
    assert saved_row["answer"] == f"'{answer}"
    assert json.loads(saved_row["answer_value_json"]) == answer


def test_write_quest_answer_log_writes_header_for_empty_history(
    tmp_path: Path,
) -> None:
    """Create a usable CSV even when the activity has no quest answers."""
    destination = write_quest_answer_log(
        [],
        tmp_path,
        "sample-event",
        "walkabout",
    )

    with destination.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames is not None
        assert "question" in reader.fieldnames
        assert "answer" in reader.fieldnames
        assert list(reader) == []
