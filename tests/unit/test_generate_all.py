"""Tests for the versioned report output directory structure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mm.publication import default_anonymized_root
from utilities import generate_all


def test_generate_all_uses_sibling_versioned_output_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write full and anonymized output beneath sibling versioned roots."""
    version = "1.2.3"
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_all, "ROOT", tmp_path)
    configs: list[generate_all.EventConfig] = [
        (
            tmp_path / "configs" / "events" / "2026-01-01-sample-one" / "event.json",
            {"id": "2026-01-01-sample-one", "activities": []},
        ),
        (
            tmp_path / "configs" / "events" / "2026-01-02-sample-two" / "event.json",
            {"id": "2026-01-02-sample-two", "activities": []},
        ),
    ]

    def discover_configs(config_root: Path) -> list[generate_all.EventConfig]:
        assert config_root == tmp_path / "configs" / "events"
        return configs

    monkeypatch.setattr(generate_all, "_discover_event_configs", discover_configs)

    cli_calls: list[list[str]] = []

    def record_cli_call(arguments: list[str]) -> int:
        cli_calls.append(arguments)
        return 0

    monkeypatch.setattr(generate_all, "run_cli", record_cli_call)
    anonymized_roots: list[tuple[Path, Path]] = []

    anonymized_event_ids: list[str] = []

    def record_anonymized_roots(
        config: dict[str, Any],
        full_root: Path,
        anonymized_root: Path,
    ) -> None:
        anonymized_roots.append((full_root, anonymized_root))
        anonymized_event_ids.append(config["id"])

    monkeypatch.setattr(
        generate_all,
        "_render_anonymized_event",
        record_anonymized_roots,
    )

    def aggregate_reports(
        paths: list[Path],
        *,
        title: str,
    ) -> dict[str, Any]:
        assert paths == []
        assert title == "SAMPLE Aggregate Contribution Report"
        return {}

    def render_aggregate_report(stats: dict[str, Any]) -> str:
        assert stats == {}
        return "<html></html>"

    monkeypatch.setattr(generate_all, "aggregate_reports", aggregate_reports)
    monkeypatch.setattr(
        generate_all,
        "render_aggregate_report",
        render_aggregate_report,
    )
    aggregate_output_roots: list[Path] = []
    aggregate_reports_written: list[tuple[dict[str, Any], str, Path, str]] = []

    def record_aggregate_output(
        stats: dict[str, Any],
        html: str,
        output_root: Path,
        series: str,
    ) -> None:
        aggregate_output_roots.append(output_root)
        aggregate_reports_written.append((stats, html, output_root, series))

    monkeypatch.setattr(
        generate_all,
        "write_aggregate_report",
        record_aggregate_output,
    )
    anonymized_aggregate_roots: list[tuple[Path, Path]] = []
    anonymized_series_ids: list[list[str]] = []

    def record_anonymized_aggregate_roots(
        series_ids: list[str],
        full_root: Path,
        anonymized_root: Path,
    ) -> None:
        anonymized_aggregate_roots.append((full_root, anonymized_root))
        anonymized_series_ids.append(series_ids)

    monkeypatch.setattr(
        generate_all,
        "_render_anonymized_aggregates",
        record_anonymized_aggregate_roots,
    )

    assert generate_all.main([]) == 0

    full_root = tmp_path / "local-output" / "v1.2.3" / "full"
    anonymized_root = tmp_path / "local-output" / "v1.2.3" / "anonymized"
    for arguments in cli_calls:
        output_index = arguments.index("--output-dir") + 1
        assert arguments[output_index] == str(full_root)
    assert anonymized_roots == [(full_root, anonymized_root)] * len(configs)
    assert anonymized_event_ids == [
        "2026-01-01-sample-one",
        "2026-01-02-sample-two",
    ]
    assert aggregate_output_roots == [full_root / "events"]
    assert aggregate_reports_written == [
        ({}, "<html></html>", full_root / "events", "sample")
    ]
    assert anonymized_aggregate_roots == [(full_root, anonymized_root)]
    assert anonymized_series_ids == [["sample"]]


def test_discovery_excludes_configs_marked_not_for_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft event configs do not participate in the public generation flow."""
    monkeypatch.setattr(generate_all, "ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    public_path = tmp_path / "configs" / "events" / "public" / "event.json"
    draft_path = tmp_path / "configs" / "events" / "draft" / "event.json"
    public_path.parent.mkdir(parents=True)
    draft_path.parent.mkdir(parents=True)
    public_path.write_text("{}\n", encoding="utf-8")
    draft_path.write_text("{}\n", encoding="utf-8")

    configs: dict[Path, dict[str, Any]] = {
        public_path: {"id": "public-event"},
        draft_path: {"id": "draft-event", "publish": False},
    }

    def load_config(path: Path) -> dict[str, Any]:
        return configs[path]

    monkeypatch.setattr(generate_all, "load_event_config", load_config)
    cli_config_paths: list[str] = []

    def record_cli_call(arguments: list[str]) -> int:
        config_index = arguments.index("--config") + 1
        cli_config_paths.append(arguments[config_index])
        return 0

    monkeypatch.setattr(generate_all, "run_cli", record_cli_call)
    rendered_events: list[tuple[str, Path, Path]] = []

    def record_anonymized_event(
        config: dict[str, Any],
        full_root: Path,
        anonymized_root: Path,
    ) -> None:
        rendered_events.append((config["id"], full_root, anonymized_root))

    monkeypatch.setattr(
        generate_all,
        "_render_anonymized_event",
        record_anonymized_event,
    )

    assert generate_all.main([]) == 0
    assert cli_config_paths == [str(public_path)]
    assert rendered_events == [
        (
            "public-event",
            tmp_path / "local-output" / "v1.2.3" / "full",
            tmp_path / "local-output" / "v1.2.3" / "anonymized",
        )
    ]


def test_publication_default_uses_versioned_anonymized_root(
    tmp_path: Path,
) -> None:
    """Use the generator's versioned anonymized directory for publication."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\n',
        encoding="utf-8",
    )

    assert default_anonymized_root(tmp_path) == (
        tmp_path / "local-output" / "v1.2.3" / "anonymized"
    )
