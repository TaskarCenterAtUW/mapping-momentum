"""End-to-end tests for the synthetic offline examples."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from example.run_offline import run_offline
from mm.common.io import read_json, write_json
from mm.pipeline import get_report_feature

EXAMPLE_ROOT = Path(__file__).parents[2] / "example"


def _identity_names(stats: dict[str, Any]) -> set[str]:
    """Collect names exposed by contributor, marker, and quote fields."""
    names = {
        contributor["user"]
        for contributor in stats.get("contributors_breakdown", [])
        if contributor.get("user")
    }
    for marker in stats.get("markers", []):
        if marker.get("user"):
            names.add(marker["user"])
        names.update(
            version["user"]
            for version in marker.get("versions", [])
            if version.get("user")
        )
    for quote in stats.get("quotes", []):
        parts = [
            quote.get("first_name", "").strip(),
            quote.get("last_name", "").strip(),
        ]
        name = " ".join(part for part in parts if part)
        if name:
            names.add(name)
    return names


def test_minimal_example_runs_end_to_end(tmp_path: Path) -> None:
    stats_path, report_path = run_offline(
        EXAMPLE_ROOT / "minimal",
        tmp_path / "minimal-output",
    )

    stats = read_json(stats_path)
    assert stats["changeset_count"] == 1
    assert stats["note_count"] == 0
    assert len(stats["markers"]) == 1
    assert report_path.read_text(encoding="utf-8").count("<html") == 1


def test_maximal_example_runs_every_report_feature(tmp_path: Path) -> None:
    stats_path, report_path = run_offline(
        EXAMPLE_ROOT / "maximal",
        tmp_path / "maximal-output",
    )

    stats = read_json(stats_path)
    html = report_path.read_text(encoding="utf-8")
    assert stats["changeset_count"] == 3
    assert stats["note_count"] == 2
    assert len(stats["pictures"]) == 2
    assert len(stats["quotes"]) == 2
    assert len(stats["slideshow_images"]) == 2
    assert stats["video_url"].endswith("synthetic-mapping.mp4")
    assert "Synthetic Maximal Contribution Report" in html
    assert "Synthetic maps help us practice careful observation." in html
    assert "https://assets.example.invalid/slideshow/01.svg" in html
    assert "https://video.example.invalid/synthetic-mapping.mp4" in html


@pytest.mark.parametrize("example_name", ["minimal", "maximal"])
def test_offline_examples_generate_anonymized_reports(
    example_name: str,
    tmp_path: Path,
) -> None:
    """Anonymize names in the stats and HTML for each sample event."""
    event_dir = EXAMPLE_ROOT / example_name
    raw_stats_path, _ = run_offline(event_dir, tmp_path / "raw")
    anonymized_stats_path, report_path = run_offline(
        event_dir,
        tmp_path / "anonymized",
        anonymize=True,
    )
    raw_stats = read_json(raw_stats_path)
    anonymized_stats = read_json(anonymized_stats_path)
    stats_json = json.dumps(anonymized_stats, ensure_ascii=False)
    html = report_path.read_text(encoding="utf-8")

    assert anonymized_stats["contributor_count"] == raw_stats["contributor_count"]
    assert anonymized_stats["changeset_count"] == raw_stats["changeset_count"]
    assert [
        contributor["user"]
        for contributor in anonymized_stats["contributors_breakdown"]
    ] == [
        f"Participant {index}"
        for index in range(1, len(raw_stats["contributors_breakdown"]) + 1)
    ]
    assert all(
        marker["user"].startswith("Participant ")
        for marker in anonymized_stats["markers"]
        if marker.get("user")
    )
    assert all(
        version["user"].startswith("Participant ")
        for marker in anonymized_stats["markers"]
        for version in marker.get("versions", [])
        if version.get("user")
    )
    assert all(
        not quote["last_name"] and quote["first_name"].startswith("Participant ")
        for quote in anonymized_stats["quotes"]
        if quote["first_name"] or quote["last_name"]
    )
    for name in _identity_names(raw_stats):
        assert name not in stats_json
        assert name not in html


def test_offline_example_filters_changesets_to_activity_window(tmp_path: Path) -> None:
    example_dir = tmp_path / "maximal"
    shutil.copytree(EXAMPLE_ROOT / "maximal", example_dir)
    event_path = example_dir / "event.json"
    event = read_json(event_path)
    event["activities"][0]["time_window"]["end"] = "2026-10-02T10:30:00Z"
    write_json(event_path, event)

    stats_path, _ = run_offline(example_dir, tmp_path / "output")

    stats = read_json(stats_path)
    assert stats["changeset_count"] == 1


def test_nested_report_features_override_event_scope() -> None:
    config = {
        "pictures": ["event.jpg"],
        "report": {"pictures": ["report.jpg"]},
    }

    assert get_report_feature(config, "pictures", []) == ["report.jpg"]
