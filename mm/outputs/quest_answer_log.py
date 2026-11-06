"""Export per-version quest answer changes to an archival CSV file."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Iterable, TypedDict

from mm.common.io import require_safe_path_component, write_text
from mm.quests.loader import QuestDefinition
from mm.sources.base import Version

QUEST_ANSWER_LOG_FILENAME = "quest-answer-log.csv"

_FIELDNAMES = (
    "event_id",
    "event_name",
    "activity_id",
    "activity_label",
    "workspace_id",
    "submitted_by",
    "submitted_at",
    "changeset_id",
    "action",
    "element_type",
    "element_id",
    "category",
    "question_tag",
    "question",
    "previous_answer",
    "previous_answer_value_json",
    "answer",
    "answer_value_json",
)


class QuestAnswerLogRow(TypedDict):
    """One quest-tag value change with its Workspace submission metadata."""

    event_id: str
    event_name: str
    activity_id: str
    activity_label: str
    workspace_id: int
    submitted_by: str
    submitted_at: str
    changeset_id: int
    action: str
    element_type: str
    element_id: int
    category: str
    question_tag: str
    question: str
    previous_answer: str
    previous_answer_value_json: str
    answer: str
    answer_value_json: str


def _spreadsheet_safe(value: str | int) -> str | int:
    """Prevent spreadsheet formula evaluation without changing stored values."""
    if isinstance(value, str) and value.lstrip(" \t\r\n\ufeff").startswith(
        ("=", "+", "-", "@")
    ):
        return f"'{value}"
    return value


def _display_answer(
    quest_def: QuestDefinition,
    question_tag: str,
    value: str | None,
) -> str:
    """Return a choice label when available, otherwise the raw answer."""
    if value is None:
        return ""
    return quest_def.tag_value_to_label.get(question_tag, {}).get(value, value)


def build_quest_answer_log_rows(
    histories: dict[tuple[str, int], list[Version]],
    quest_def: QuestDefinition,
    *,
    event_id: str,
    event_name: str,
    activity_id: str,
    activity_label: str,
    workspace_id: int,
) -> list[QuestAnswerLogRow]:
    """Build an ordered row for each changed quest answer in *histories*."""
    rows: list[QuestAnswerLogRow] = []
    question_tags = sorted(quest_def.tag_to_title)

    for (element_type, element_id), versions in sorted(histories.items()):
        previous_tags: dict[str, str] = {}
        for version in versions:
            current_tags = version["tags"]
            for question_tag in question_tags:
                previous_value = previous_tags.get(question_tag)
                answer_value = current_tags.get(question_tag)
                if previous_value == answer_value:
                    continue

                rows.append(
                    {
                        "event_id": event_id,
                        "event_name": event_name,
                        "activity_id": activity_id,
                        "activity_label": activity_label,
                        "workspace_id": workspace_id,
                        "submitted_by": version["user"],
                        "submitted_at": version["timestamp"],
                        "changeset_id": version["changeset"],
                        "action": version["action"],
                        "element_type": element_type,
                        "element_id": element_id,
                        "category": quest_def.tag_to_category.get(question_tag, ""),
                        "question_tag": question_tag,
                        "question": quest_def.tag_to_title.get(
                            question_tag, question_tag
                        ),
                        "previous_answer": _display_answer(
                            quest_def, question_tag, previous_value
                        ),
                        "previous_answer_value_json": json.dumps(
                            previous_value, ensure_ascii=False
                        ),
                        "answer": _display_answer(
                            quest_def, question_tag, answer_value
                        ),
                        "answer_value_json": json.dumps(
                            answer_value, ensure_ascii=False
                        ),
                    }
                )
            previous_tags = current_tags

    rows.sort(
        key=lambda row: (
            row["submitted_at"],
            row["changeset_id"],
            row["element_type"],
            row["element_id"],
            row["question_tag"],
        )
    )
    return rows


def write_quest_answer_log(
    rows: Iterable[QuestAnswerLogRow],
    output_dir: Path,
    event_id: str,
    activity_id: str,
) -> Path:
    """Write the answer log beside an activity's stats and report."""
    safe_event_id = require_safe_path_component(event_id, "event_id")
    safe_activity_id = require_safe_path_component(activity_id, "activity_id")
    destination = (
        output_dir
        / "events"
        / safe_event_id
        / safe_activity_id
        / QUEST_ANSWER_LOG_FILENAME
    )
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(_FIELDNAMES)
    for row in rows:
        writer.writerow(
            _spreadsheet_safe(value)
            for value in (
                row["event_id"],
                row["event_name"],
                row["activity_id"],
                row["activity_label"],
                row["workspace_id"],
                row["submitted_by"],
                row["submitted_at"],
                row["changeset_id"],
                row["action"],
                row["element_type"],
                row["element_id"],
                row["category"],
                row["question_tag"],
                row["question"],
                row["previous_answer"],
                row["previous_answer_value_json"],
                row["answer"],
                row["answer_value_json"],
            )
        )
    write_text(destination, buffer.getvalue())
    return destination
