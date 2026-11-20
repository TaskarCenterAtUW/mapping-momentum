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

    aggregate_titles: list[str] = []

    def aggregate_reports(
        paths: list[Path],
        *,
        title: str,
    ) -> dict[str, Any]:
        assert paths == []
        aggregate_titles.append(title)
        return {"title": title}

    def render_aggregate_report(stats: dict[str, Any]) -> str:
        assert "title" in stats
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
    assert aggregate_output_roots == [full_root / "events"] * 2
    assert aggregate_titles == [
        "SAMPLE Aggregate Contribution Report",
        "All Events Aggregate Contribution Report",
    ]
    assert aggregate_reports_written == [
        (
            {"title": "SAMPLE Aggregate Contribution Report"},
            "<html></html>",
            full_root / "events",
            "sample",
        ),
        (
            {"title": "All Events Aggregate Contribution Report"},
            "<html></html>",
            full_root / "events",
            "all",
        ),
    ]
    assert anonymized_aggregate_roots == [(full_root, anonymized_root)]
    assert anonymized_series_ids == [["sample", "all"]]


def test_all_aggregate_includes_configs_without_a_series(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Include standalone configured events in the all-events aggregate."""
    monkeypatch.setattr(generate_all, "ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    config_root = tmp_path / "configs" / "events"
    series_configs: list[generate_all.EventConfig] = [
        (
            config_root / "2026-01-01-srts-one" / "event.json",
            {"id": "2026-01-01-srts-one", "activities": [{"id": "walkabout"}]},
        ),
        (
            config_root / "2026-01-02-srts-two" / "event.json",
            {"id": "2026-01-02-srts-two", "activities": [{"id": "walkabout"}]},
        ),
    ]
    standalone_config: generate_all.EventConfig = (
        config_root / "standalone-event" / "event.json",
        {"id": "standalone-event", "activities": [{"id": "walkabout"}]},
    )
    configs = [*series_configs, standalone_config]
    configs_by_path: dict[Path, dict[str, Any]] = {}
    for config_path, config in configs:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}\n", encoding="utf-8")
        configs_by_path[config_path] = config

    def load_config(config_path: Path) -> dict[str, Any]:
        return configs_by_path[config_path]

    monkeypatch.setattr(generate_all, "load_event_config", load_config)

    def write_event_stats(arguments: list[str]) -> int:
        config_path = Path(arguments[arguments.index("--config") + 1])
        output_root = Path(arguments[arguments.index("--output-dir") + 1])
        config = configs_by_path[config_path]
        for activity in config["activities"]:
            stats_path = (
                output_root / "events" / config["id"] / activity["id"] / "stats.json"
            )
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            stats_path.write_text("{}\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(generate_all, "run_cli", write_event_stats)

    aggregate_calls: list[tuple[list[Path], str]] = []
    written_aggregate_ids: list[str] = []

    def aggregate_reports(
        paths: list[Path],
        *,
        title: str,
    ) -> dict[str, Any]:
        aggregate_calls.append((paths, title))
        return {"title": title}

    def render_aggregate_report(stats: dict[str, Any]) -> str:
        title = stats.get("title")
        assert isinstance(title, str)
        return title

    monkeypatch.setattr(generate_all, "aggregate_reports", aggregate_reports)
    monkeypatch.setattr(
        generate_all,
        "render_aggregate_report",
        render_aggregate_report,
    )

    def write_aggregate_report(
        stats: dict[str, Any],
        html: str,
        output_dir: Path,
        report_id: str,
    ) -> Path:
        title = stats.get("title")
        assert isinstance(title, str)
        assert html == title
        written_aggregate_ids.append(report_id)
        return output_dir / "aggregates" / report_id / "index.html"

    monkeypatch.setattr(
        generate_all,
        "write_aggregate_report",
        write_aggregate_report,
    )

    def skip_anonymized_event(
        _config: dict[str, Any],
        _full_root: Path,
        _anonymized_root: Path,
    ) -> None:
        return None

    def skip_anonymized_aggregates(
        _aggregate_ids: list[str],
        _full_root: Path,
        _anonymized_root: Path,
    ) -> None:
        return None

    monkeypatch.setattr(
        generate_all,
        "_render_anonymized_event",
        skip_anonymized_event,
    )
    monkeypatch.setattr(
        generate_all,
        "_render_anonymized_aggregates",
        skip_anonymized_aggregates,
    )

    assert generate_all.main([]) == 0

    full_root = tmp_path / "local-output" / "v1.2.3" / "full"
    stats_paths = [
        full_root / "events" / config["id"] / activity["id"] / "stats.json"
        for _, config in configs
        for activity in config["activities"]
    ]

    assert aggregate_calls == [
        (
            stats_paths[:2],
            "SRTS Aggregate Contribution Report",
        ),
        (
            stats_paths,
            "All Events Aggregate Contribution Report",
        ),
    ]
    assert written_aggregate_ids == ["srts", "all"]


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

    def skip_aggregates(
        _groups: dict[str, list[generate_all.EventConfig]],
        _full_root: Path,
        _configs: list[generate_all.EventConfig],
    ) -> list[str]:
        return []

    monkeypatch.setattr(
        generate_all,
        "_generate_non_anonymized_aggregates",
        skip_aggregates,
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
