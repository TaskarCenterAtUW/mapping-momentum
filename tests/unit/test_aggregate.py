"""Tests for cross-event aggregation of generated report statistics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from example.run_offline import run_offline
from mm.cli import run_cli
from mm.outputs.aggregate import aggregate_reports
from mm.outputs.html_report import render_aggregate_report
from mm.outputs.json_stats import build_stats
from mm.sources.base import Element, SourceResult

UTC = timezone.utc
EXAMPLE_ROOT = Path(__file__).parents[2] / "example"


def _report_stats(
    event_id: str,
    event_name: str,
    *,
    start: str,
    quest_answers: int,
    notes: int,
    contributions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a small per-event stats payload for aggregation tests."""
    contributors: list[dict[str, Any]] = [
        {
            "user": item["user"],
            "count": item["quest_answer_count"] + item["note_count"],
            "photo_count": 0,
        }
        for item in contributions
    ]
    return {
        "source_type": "workspace",
        "event_id": event_id,
        "event_name": event_name,
        "activity_id": "walkabout",
        "activity_label": "Walk/Roll",
        "window_start": start,
        "window_end": start.replace("T00:00:00", "T23:59:59"),
        "changeset_count": quest_answers,
        "note_count": notes,
        "contributor_count": len(contributions),
        "contributors_breakdown": contributors,
        "contributions_by_user": contributions,
        "quest_type_breakdown": [
            {"category": "Sidewalks", "count": quest_answers, "photo_count": 0}
        ],
        "features_created": [{"feature_type": "node", "count": 1}],
        "markers": [
            {
                "id": 1,
                "type": "node",
                "kind": "quest",
                "category": "Sidewalks",
                "lat": 47.6,
                "lon": -122.3,
                "user": contributions[0]["user"] if contributions else "",
                "versions": [
                    {
                        "user": contributions[0]["user"],
                        "changeset": 100,
                    }
                ]
                if contributions
                else [],
            }
        ],
    }


def _write_report(directory: Path, stats: dict[str, Any]) -> Path:
    """Write stats.json in a report directory and return its path."""
    directory.mkdir(parents=True)
    stats_path = directory / "stats.json"
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    return stats_path


def _quest_element(id_: int, user: str, changeset: int) -> dict[str, Any]:
    """Build a minimal enriched quest element with one changeset version."""
    return {
        "type": "node",
        "id": id_,
        "timestamp": "2026-01-20T20:00:00Z",
        "user": user,
        "uid": id_,
        "changeset": changeset,
        "tags": {},
        "lat": 47.6,
        "lon": -122.3,
        "kind": "quest",
        "category": "Sidewalks",
        "versions": [
            {
                "action": "modify",
                "user": user,
                "timestamp": "2026-01-20T20:00:00Z",
                "changeset": changeset,
                "tags": {},
                "readable": {},
                "photos": [],
            }
        ],
        "photos": [],
        "readable": {},
        "geom": None,
    }


def test_build_stats_counts_distinct_quest_changesets_per_user() -> None:
    """Count one quest answer per changeset and attribute notes to their author."""
    elements: list[Element] = [
        _quest_element(1, "alice", 100),
        _quest_element(2, "alice", 100),
        _quest_element(3, "alice", 101),
        {
            "type": "note",
            "id": 99,
            "timestamp": "2026-01-20T21:00:00Z",
            "user": "alice",
            "uid": 10,
            "changeset": 0,
            "tags": {},
            "lat": 47.6,
            "lon": -122.3,
            "kind": "note",
            "category": "",
            "versions": [],
            "photos": [],
            "readable": {},
            "geom": None,
            "text": "A note",
        },
    ]
    elements[0]["changeset"] = 900
    elements[1]["changeset"] = 901
    elements[2]["changeset"] = 902
    result = SourceResult(
        source_type="workspace",
        activity_id="walkabout",
        window_start=datetime(2026, 1, 20, tzinfo=UTC),
        window_end=datetime(2026, 1, 21, tzinfo=UTC),
        elements=elements,
    )

    stats = build_stats(result)

    assert stats["contributions_by_user"] == [
        {"user": "alice", "quest_answer_count": 2, "note_count": 1}
    ]
    assert stats["changeset_count"] == 2


def test_aggregate_reports_merges_contributor_and_sums_quest_answers(
    tmp_path: Path,
) -> None:
    """Merge a contributor's answers across reports without double-counting them."""
    first = _report_stats(
        "event-one",
        "Event One",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=2,
        notes=1,
        contributions=[{"user": "alice", "quest_answer_count": 2, "note_count": 1}],
    )
    second = _report_stats(
        "event-two",
        "Event Two",
        start="2026-02-20T00:00:00+00:00",
        quest_answers=3,
        notes=2,
        contributions=[{"user": "alice", "quest_answer_count": 3, "note_count": 2}],
    )
    first_path = _write_report(tmp_path / "events" / "event-one" / "walkabout", first)
    second_path = _write_report(
        tmp_path / "events" / "event-two" / "walkabout",
        second,
    )

    aggregate = aggregate_reports(
        [first_path.parent, second_path],
        title="Two Events",
    )

    assert aggregate["contributor_count"] == 1
    assert aggregate["quest_answer_count"] == 5
    assert aggregate["note_count"] == 3
    assert aggregate["unattributed_note_count"] == 0
    assert aggregate["event_count"] == 2
    assert aggregate["contributions_by_user"] == [
        {
            "user": "alice",
            "quest_answer_count": 5,
            "note_count": 3,
            "contribution_count": 8,
        }
    ]
    assert aggregate["quest_type_breakdown"] == [
        {"category": "Sidewalks", "count": 5, "photo_count": 0}
    ]
    assert aggregate["new_feature_count"] == 2
    assert [event["event_name"] for event in aggregate["events"]] == [
        "Event One",
        "Event Two",
    ]
    assert aggregate["markers"][0]["event_name"] == "Event One"


def test_aggregate_reports_accepts_generated_offline_reports(tmp_path: Path) -> None:
    """Aggregate stats emitted by the complete offline event-report pipeline."""
    minimal_stats_path, _ = run_offline(
        EXAMPLE_ROOT / "minimal",
        tmp_path / "minimal-output",
    )
    maximal_stats_path, _ = run_offline(
        EXAMPLE_ROOT / "maximal",
        tmp_path / "maximal-output",
    )
    source_stats = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (minimal_stats_path, maximal_stats_path)
    ]

    aggregate = aggregate_reports([minimal_stats_path, maximal_stats_path])

    assert aggregate["event_count"] == 2
    assert aggregate["report_count"] == 2
    assert aggregate["quest_answer_count"] == sum(
        stats["changeset_count"] for stats in source_stats
    )
    assert {event["event_name"] for event in aggregate["events"]} == {
        stats["event_name"] for stats in source_stats
    }


def test_aggregate_reports_derives_contributors_from_legacy_markers(
    tmp_path: Path,
) -> None:
    """Recover per-user quest and note totals from older report marker histories."""
    stats = _report_stats(
        "legacy-event",
        "Legacy Event",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=2,
        notes=1,
        contributions=[],
    )
    stats.pop("contributions_by_user")
    stats["contributor_count"] = 2
    stats["contributors_breakdown"] = [
        {"user": "alice", "count": 2, "photo_count": 0},
        {"user": "bob", "count": 1, "photo_count": 0},
    ]
    stats["markers"] = [
        {
            "kind": "quest",
            "user": "alice",
            "versions": [{"user": "alice", "changeset": 100}],
        },
        {
            "kind": "quest",
            "user": "alice",
            "versions": [{"user": "alice", "changeset": 100}],
        },
        {
            "kind": "quest",
            "user": "alice",
            "versions": [{"user": "alice", "changeset": 101}],
        },
        {"kind": "note", "user": "bob", "versions": []},
    ]
    stats_path = _write_report(tmp_path / "legacy", stats)

    aggregate = aggregate_reports([stats_path])

    assert aggregate["contributor_count"] == 2
    assert aggregate["unattributed_note_count"] == 0
    assert aggregate["contributions_by_user"] == [
        {
            "user": "alice",
            "quest_answer_count": 2,
            "note_count": 0,
            "contribution_count": 2,
        },
        {
            "user": "bob",
            "quest_answer_count": 0,
            "note_count": 1,
            "contribution_count": 1,
        },
    ]


def test_aggregate_reports_uses_legacy_histories_when_stored_total_is_lower(
    tmp_path: Path,
) -> None:
    """Use complete legacy histories when their stored changeset total is stale."""
    stats = _report_stats(
        "legacy-event",
        "Legacy Event",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=0,
        notes=0,
        contributions=[],
    )
    stats.pop("contributions_by_user")
    stats["contributor_count"] = 1
    stats["contributors_breakdown"] = [
        {"user": "alice", "count": 1, "photo_count": 0}
    ]
    stats["markers"] = [
        {
            "kind": "quest",
            "user": "alice",
            "versions": [{"user": "alice", "changeset": 100}],
        },
    ]
    stats_path = _write_report(tmp_path / "legacy", stats)

    aggregate = aggregate_reports([stats_path])
    html = " ".join(render_aggregate_report(aggregate).split())

    assert aggregate["quest_answer_count"] == 1
    assert aggregate["changeset_count"] == 1
    assert aggregate["reported_changeset_count"] == 0
    assert aggregate["legacy_quest_count_mismatch_event_count"] == 1
    assert aggregate["events"][0]["quest_answer_count"] == 1
    assert aggregate["events"][0]["reported_changeset_count"] == 0
    assert "uses the marker-history totals (1 quest answers)" in html
    assert "the source stats report 0 changesets" in html


def test_aggregate_reports_preserves_notes_without_legacy_authors(
    tmp_path: Path,
) -> None:
    """Keep global note totals when old markers do not identify their authors."""
    stats = _report_stats(
        "legacy-event",
        "Legacy Event",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=1,
        notes=2,
        contributions=[],
    )
    stats.pop("contributions_by_user")
    stats["contributor_count"] = 1
    stats["contributors_breakdown"] = [
        {"user": "alice", "count": 1, "photo_count": 0}
    ]
    stats["markers"] = [
        {
            "kind": "quest",
            "user": "alice",
            "versions": [{"user": "alice", "changeset": 100}],
        },
        {"kind": "note", "user": "", "versions": []},
        {"kind": "note", "user": "", "versions": []},
    ]
    stats_path = _write_report(tmp_path / "legacy", stats)

    aggregate = aggregate_reports([stats_path])
    html = render_aggregate_report(aggregate)

    assert aggregate["note_count"] == 2
    assert aggregate["unattributed_note_count"] == 2
    assert aggregate["events"][0]["unattributed_note_count"] == 2
    assert aggregate["contributions_by_user"][0]["note_count"] == 0
    assert "2 notes are included in the total" in html
    assert "could not be attributed to individual contributors" in " ".join(
        html.split()
    )


def test_aggregate_report_places_map_before_contributors_and_syncs_theme(
    tmp_path: Path,
) -> None:
    """Render the map first and select its basemap from the active theme."""
    stats = _report_stats(
        "layout-event",
        "Layout Event",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=1,
        notes=0,
        contributions=[
            {"user": "alice", "quest_answer_count": 1, "note_count": 0}
        ],
    )
    stats_path = _write_report(tmp_path / "layout", stats)
    html = render_aggregate_report(aggregate_reports([stats_path]))

    assert html.index('aria-labelledby="map-heading"') < html.index(
        'aria-labelledby="contributors-heading"'
    )
    assert "Source reports must be non-anonymized" not in html
    assert "theme === 'dark' ? 'fiord' : 'positron'" in html
    assert "syncMapStyle(document.documentElement.dataset.theme);" in html
    assert "syncMapStyle(nextTheme);" in html
    assert html.index("syncMapStyle(document.documentElement.dataset.theme);") < (
        html.index("const map = new maplibregl.Map")
    )


@pytest.mark.parametrize(
    ("anonymized", "user"),
    [(True, "alice"), (False, "Participant 1")],
)
def test_aggregate_reports_rejects_anonymized_sources(
    tmp_path: Path,
    anonymized: bool,
    user: str,
) -> None:
    """Refuse explicit or legacy-anonymized stats that cannot deduplicate users."""
    stats = _report_stats(
        "event-one",
        "Event One",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=1,
        notes=0,
        contributions=[{"user": user, "quest_answer_count": 1, "note_count": 0}],
    )
    if anonymized:
        stats["anonymized"] = True
    stats_path = _write_report(tmp_path / str(anonymized), stats)

    with pytest.raises(ValueError, match="anonymized"):
        aggregate_reports([stats_path])


def test_aggregate_cli_writes_anonymized_summary_without_changing_sources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Create a complete HTML report and anonymize only after contributor merging."""
    first_path = _write_report(
        tmp_path / "event-one",
        _report_stats(
            "event-one",
            "Event One",
            start="2026-01-20T00:00:00+00:00",
            quest_answers=2,
            notes=0,
            contributions=[{"user": "alice", "quest_answer_count": 2, "note_count": 0}],
        ),
    )
    second_path = _write_report(
        tmp_path / "event-two",
        _report_stats(
            "event-two",
            "Event Two",
            start="2026-02-20T00:00:00+00:00",
            quest_answers=3,
            notes=0,
            contributions=[{"user": "alice", "quest_answer_count": 3, "note_count": 0}],
        ),
    )
    output_root = tmp_path / "output"

    result = run_cli(
        [
            "aggregate",
            "--reports",
            str(first_path),
            str(second_path),
            "--report-id",
            "two-event-summary",
            "--title",
            "Two Event Contribution Summary",
            "--output-dir",
            str(output_root),
            "--anonymize",
        ]
    )

    output = output_root / "aggregates" / "two-event-summary"
    report_stats = json.loads((output / "stats.json").read_text(encoding="utf-8"))
    html = (output / "index.html").read_text(encoding="utf-8")
    capsys.readouterr()

    assert result == 0
    assert report_stats["contributor_count"] == 1
    assert report_stats["contributions_by_user"][0]["quest_answer_count"] == 5
    assert report_stats["anonymized"] is True
    assert "Two Event Contribution Summary" in html
    assert "Contributions by event" in html
    assert "Contribution mix by element type" in html
    assert "Where it happened" in html
    assert "alice" not in html
    assert "Participant 1" in html
    source_stats = json.loads(first_path.read_text(encoding="utf-8"))
    assert source_stats["contributions_by_user"][0]["user"] == "alice"


def test_aggregate_reports_rejects_duplicate_source_report(
    tmp_path: Path,
) -> None:
    """Reject duplicate source reports instead of silently doubling totals."""
    stats = _report_stats(
        "event-one",
        "Event One",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=1,
        notes=0,
        contributions=[{"user": "alice", "quest_answer_count": 1, "note_count": 0}],
    )
    first_path = _write_report(tmp_path / "first", stats)
    second_path = _write_report(tmp_path / "second", stats)

    with pytest.raises(ValueError, match="duplicate report"):
        aggregate_reports([first_path, second_path])


def test_aggregate_reports_rejects_inconsistent_contributor_totals(
    tmp_path: Path,
) -> None:
    """Do not publish totals that cannot be reconciled with contributor histories."""
    stats = _report_stats(
        "event-one",
        "Event One",
        start="2026-01-20T00:00:00+00:00",
        quest_answers=2,
        notes=0,
        contributions=[{"user": "alice", "quest_answer_count": 1, "note_count": 0}],
    )
    stats_path = _write_report(tmp_path / "inconsistent", stats)

    with pytest.raises(ValueError, match="do not match changeset_count"):
        aggregate_reports([stats_path])
