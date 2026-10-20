"""Tests for the authenticated Workspace report pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mm import pipeline


def test_run_activity_uses_provided_access_token(
    tmp_path: Path, monkeypatch
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
    activity = {
        "id": "walkabout",
        "type": "workspace",
        "environment": "stage",
        "workspace_id": 931,
        "time_window": {
            "start": "2026-01-20T18:00:00Z",
            "end": "2026-01-21T04:00:00Z",
        },
    }
    monkeypatch.setattr(pipeline, "load_quest_definition", lambda _path: object())
    request_calls = []

    def fake_bbox(env: str, workspace_id: int, token: str) -> tuple[float, ...]:
        request_calls.append(("bbox", env, workspace_id, token))
        return (-122.5, 49.0, -122.4, 49.1)

    def fake_map(
        env: str,
        workspace_id: int,
        bbox: tuple[float, ...],
        token: str,
    ) -> bytes:
        request_calls.append(("map", env, workspace_id, token))
        return b"<osm/>"

    def fake_changesets(
        env: str,
        workspace_id: int,
        _start,
        _end,
        token: str,
    ) -> list[dict[str, Any]]:
        request_calls.append(("changesets", env, workspace_id, token))
        return []

    def fake_notes(env: str, workspace_id: int, token: str) -> list[dict[str, Any]]:
        request_calls.append(("notes", env, workspace_id, token))
        return []

    monkeypatch.setattr(pipeline, "fetch_bbox", fake_bbox)
    monkeypatch.setattr(pipeline, "fetch_osm_xml", fake_map)
    monkeypatch.setattr(pipeline, "parse_osm_xml", lambda _payload: [])
    monkeypatch.setattr(pipeline, "fetch_changesets", fake_changesets)
    monkeypatch.setattr(pipeline, "build_version_histories", lambda *_a, **_k: {})
    monkeypatch.setattr(pipeline, "enrich_elements", lambda *_a, **_k: [])
    monkeypatch.setattr(pipeline, "resolve_way_geometry", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "fetch_notes", fake_notes)
    monkeypatch.setattr(pipeline, "parse_notes", lambda *_a, **_k: [])
    monkeypatch.setattr(pipeline, "build_stats", lambda *_a, **_k: {"ok": True})

    stats = pipeline.run_activity(
        config,
        activity,
        output_dir=tmp_path / "unused-output",
        access_token="stage-access-token",
        dry_run=True,
    )

    assert stats == {"ok": True}
    assert request_calls == [
        ("bbox", "stage", 931, "stage-access-token"),
        ("map", "stage", 931, "stage-access-token"),
        ("changesets", "stage", 931, "stage-access-token"),
        ("notes", "stage", 931, "stage-access-token"),
    ]
