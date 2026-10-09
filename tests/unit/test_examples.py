"""End-to-end tests for the synthetic offline examples."""

from __future__ import annotations

from pathlib import Path

from example.run_offline import run_offline
from mm.common.io import read_json

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
