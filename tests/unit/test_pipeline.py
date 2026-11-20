"""Tests for the authenticated Workspace report pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from mm import pipeline
from mm.quests.loader import QuestDefinition
from mm.sources.base import Element, SourceResult, Version
from mm.sources.workspace import BBox


def test_run_activity_uses_provided_access_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass the CLI-provided token to every Workspace request."""
    event_dir = tmp_path
    quest_path = event_dir / "quest-definitions" / "walkabout.json"
    quest_path.parent.mkdir()
    quest_path.write_text("{}", encoding="utf-8")
    config: dict[str, Any] = {
        "_event_dir": event_dir,
        "id": "sample-event",
    }
    activity: dict[str, Any] = {
        "id": "walkabout",
        "type": "workspace",
        "environment": "stage",
        "workspace_id": 931,
        "time_window": {
            "start": "2026-01-20T18:00:00Z",
            "end": "2026-01-21T04:00:00Z",
        },
    }
    expected_bbox: BBox = (-122.5, 49.0, -122.4, 49.1)
    expected_start = datetime(2026, 1, 20, 18, tzinfo=timezone.utc)
    expected_end = datetime(2026, 1, 21, 4, tzinfo=timezone.utc)
    quest_definition = QuestDefinition({}, {}, {})
    request_calls: list[tuple[str, str, int, str]] = []
    raw_stats: dict[str, Any] = {
        "ok": True,
        "contributors_breakdown": [{"user": "alice", "count": 1, "photo_count": 0}],
        "markers": [
            {
                "user": "alice",
                "versions": [{"user": "alice"}],
                "text": "Note from alice",
            }
        ],
    }

    def fake_load_quest_definition(path: str | Path) -> QuestDefinition:
        assert path == quest_path
        return quest_definition

    def fake_bbox(env: str, workspace_id: int, token: str) -> BBox:
        request_calls.append(("bbox", env, workspace_id, token))
        return expected_bbox

    def fake_map(
        env: str,
        workspace_id: int,
        bbox: BBox,
        token: str,
    ) -> bytes:
        assert bbox == expected_bbox
        request_calls.append(("map", env, workspace_id, token))
        return b"<osm/>"

    def fake_changesets(
        env: str,
        workspace_id: int,
        window_start: datetime,
        window_end: datetime,
        token: str,
    ) -> list[dict[str, Any]]:
        assert window_start == expected_start
        assert window_end == expected_end
        request_calls.append(("changesets", env, workspace_id, token))
        return []

    def fake_notes(env: str, workspace_id: int, token: str) -> list[dict[str, Any]]:
        request_calls.append(("notes", env, workspace_id, token))
        return []

    def fake_parse_osm_xml(payload: bytes) -> list[Element]:
        assert payload == b"<osm/>"
        return []

    def fake_build_version_histories(
        actions: list[tuple[str, Element]],
        *,
        quest_def: QuestDefinition,
    ) -> dict[tuple[str, int], list[Version]]:
        assert actions == []
        assert quest_def is quest_definition
        return {}

    def fake_enrich_elements(
        map_elements: list[Element],
        histories: dict[tuple[str, int], list[Version]],
        *,
        quest_def: QuestDefinition,
    ) -> list[Element]:
        assert map_elements == []
        assert histories == {}
        assert quest_def is quest_definition
        return map_elements

    def fake_resolve_way_geometry(
        elements: list[Element],
        *,
        coordinate_source: Iterable[Element] | None = None,
    ) -> None:
        assert elements == []
        assert coordinate_source is not None
        assert list(coordinate_source) == []

    def fake_parse_notes(
        raw_notes: list[dict[str, Any]],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[Element]:
        assert raw_notes == []
        assert window_start == expected_start
        assert window_end == expected_end
        return []

    def fake_build_stats(
        result: SourceResult,
        *,
        quest_def: QuestDefinition,
        showcase_photos: list[dict[str, str]],
        pictures: str | list[Any] | None,
        quotes: list[Any] | None,
        slideshow_url: str | list[str] | None,
        video_url: str | None,
        event_dir: Path | None,
    ) -> dict[str, Any]:
        assert result.activity_id == "walkabout"
        assert result.elements == []
        assert quest_def is quest_definition
        assert showcase_photos == []
        assert pictures == []
        assert quotes == []
        assert slideshow_url is None
        assert video_url is None
        assert event_dir == event_dir_expected
        return raw_stats

    event_dir_expected = event_dir
    monkeypatch.setattr(pipeline, "fetch_bbox", fake_bbox)
    monkeypatch.setattr(pipeline, "fetch_osm_xml", fake_map)
    monkeypatch.setattr(pipeline, "load_quest_definition", fake_load_quest_definition)
    monkeypatch.setattr(pipeline, "parse_osm_xml", fake_parse_osm_xml)
    monkeypatch.setattr(pipeline, "fetch_changesets", fake_changesets)
    monkeypatch.setattr(
        pipeline, "build_version_histories", fake_build_version_histories
    )
    monkeypatch.setattr(pipeline, "enrich_elements", fake_enrich_elements)
    monkeypatch.setattr(pipeline, "resolve_way_geometry", fake_resolve_way_geometry)
    monkeypatch.setattr(pipeline, "fetch_notes", fake_notes)
    monkeypatch.setattr(pipeline, "parse_notes", fake_parse_notes)
    monkeypatch.setattr(pipeline, "build_stats", fake_build_stats)

    stats = pipeline.run_activity(
        config,
        activity,
        output_dir=tmp_path / "output",
        access_token="stage-access-token",
        anonymize=True,
        include_quest_answer_log=True,
    )

    assert stats["contributors_breakdown"][0]["user"] == "Participant 1"
    assert stats["markers"][0]["user"] == "Participant 1"
    assert stats["markers"][0]["versions"][0]["user"] == "Participant 1"
    assert stats["markers"][0]["text"] == "Note from Participant 1"
    assert raw_stats["contributors_breakdown"][0]["user"] == "alice"
    output_dir = tmp_path / "output" / "events" / "sample-event" / "walkabout"
    saved_stats = output_dir / "stats.json"
    saved_html = output_dir / "index.html"
    saved_answer_log = output_dir / "quest-answer-log.csv"
    assert saved_answer_log.is_file()
    assert "question" in saved_answer_log.read_text(encoding="utf-8").splitlines()[0]
    assert "alice" not in saved_stats.read_text(encoding="utf-8")
    assert "Participant 1" in saved_html.read_text(encoding="utf-8")
    assert request_calls == [
        ("bbox", "stage", 931, "stage-access-token"),
        ("map", "stage", 931, "stage-access-token"),
        ("changesets", "stage", 931, "stage-access-token"),
        ("notes", "stage", 931, "stage-access-token"),
    ]
