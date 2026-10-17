"""End-to-end tests for the synthetic offline examples."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from example.run_offline import run_offline
from mm.common.io import read_json, write_json
from mm.config.schema import ENV_CREDENTIAL_VAR
from mm.pipeline import get_report_feature

EXAMPLE_ROOT = Path(__file__).parents[2] / "example"


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


def test_offline_run_restores_credentials(tmp_path: Path, monkeypatch) -> None:
    for env_var in ENV_CREDENTIAL_VAR.values():
        monkeypatch.delenv(env_var, raising=False)

    run_offline(EXAMPLE_ROOT / "minimal", tmp_path / "minimal-output")

    assert all(
        env_var not in os.environ for env_var in ENV_CREDENTIAL_VAR.values()
    )
