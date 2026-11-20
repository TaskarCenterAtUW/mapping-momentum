"""Regenerate configured event reports, logs, and event aggregates.

Run with the project's virtual environment active. Event configs are discovered
under ``configs/events``; the ``template`` directory is excluded. Full reports
go to ``local-output/v<project-version>/full/`` and anonymized copies go to
``local-output/v<project-version>/anonymized/``.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any, TypeGuard, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mm.cli import run_cli  # noqa: E402
from mm.common.io import read_json  # noqa: E402
from mm.config.loader import load_event_config  # noqa: E402
from mm.outputs.aggregate import aggregate_reports, write_aggregate_report  # noqa: E402
from mm.outputs.anonymize import anonymize_stats  # noqa: E402
from mm.outputs.html_report import (  # noqa: E402
    render_aggregate_report,
    render_report,
    write_report,
)
from mm.outputs.json_stats import write_stats  # noqa: E402
from mm.outputs.quest_answer_log import (  # noqa: E402
    QUEST_ANSWER_LOG_FILENAME,
    QuestAnswerLogRow,
    write_quest_answer_log,
)

EventConfig = tuple[Path, dict[str, Any]]
_EVENT_SERIES_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<series>[a-z0-9]+)(?:-|$)")


def _is_json_object(value: Any) -> TypeGuard[dict[str, Any]]:
    """Return whether a decoded JSON value is an object."""
    return isinstance(value, dict)


def _project_version() -> str:
    """Read the report output version from the root project metadata."""
    project_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project_data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml must define a non-empty project version")
    return version.strip()


def _discover_event_configs(config_root: Path) -> list[EventConfig]:
    """Load every real event config beneath *config_root*, excluding templates."""
    configs: list[EventConfig] = []
    ids_to_paths: dict[str, Path] = {}

    for config_path in sorted(config_root.rglob("event.json")):
        relative_parts = config_path.relative_to(config_root).parts[:-1]
        if any(part.casefold() == "template" for part in relative_parts):
            continue

        config = load_event_config(config_path)
        if config.get("publish", True) is False:
            continue
        event_id = config["id"]
        if event_id in ids_to_paths:
            raise ValueError(
                f"duplicate event id {event_id!r} in {ids_to_paths[event_id]} "
                f"and {config_path}"
            )
        ids_to_paths[event_id] = config_path
        configs.append((config_path, config))

    if not configs:
        raise ValueError(f"no event.json configs found under {config_root}")
    return configs


def _event_series(event_id: str) -> str | None:
    """Infer a series slug from IDs shaped like YYYY-MM-DD-series-event."""
    match = _EVENT_SERIES_PATTERN.match(event_id)
    return match.group("series") if match else None


def _group_event_series(
    configs: list[EventConfig],
) -> dict[str, list[EventConfig]]:
    """Group configs by their date-prefixed event ID series slug."""
    groups: dict[str, list[EventConfig]] = defaultdict(list)
    for entry in configs:
        series = _event_series(entry[1]["id"])
        if series:
            groups[series].append(entry)
    return dict(sorted(groups.items()))


def _activity_stats_path(
    output_root: Path,
    config: dict[str, Any],
    activity: dict[str, Any],
) -> Path:
    return output_root / "events" / config["id"] / activity["id"] / "stats.json"


def _event_outputs_complete(config: dict[str, Any], output_root: Path) -> bool:
    """Return whether every activity already has stats and its answer log."""
    for activity in config["activities"]:
        stats_path = _activity_stats_path(output_root, config, activity)
        if not stats_path.is_file():
            return False
        if not (stats_path.parent / QUEST_ANSWER_LOG_FILENAME).is_file():
            return False
    return True


def _read_answer_log(path: Path) -> list[dict[str, str]]:
    """Read a generated quest-answer CSV for anonymization and rewriting."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"quest-answer log has no header: {path}")

        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(
                    f"malformed quest-answer log row at {path}:{line_number}"
                )
            rows.append({key: value for key, value in row.items() if key is not None})
    return rows


def _render_anonymized_event(
    config: dict[str, Any],
    full_output_root: Path,
    anonymized_output_root: Path,
) -> None:
    """Copy one event's reports and quest-answer logs to anonymized output."""
    event_id = config["id"]
    for activity in config["activities"]:
        activity_id = activity["id"]
        stats_path = _activity_stats_path(full_output_root, config, activity)
        log_path = stats_path.parent / QUEST_ANSWER_LOG_FILENAME
        if not stats_path.is_file():
            raise FileNotFoundError(f"event stats not found: {stats_path}")
        if not log_path.is_file():
            raise FileNotFoundError(f"quest-answer log not found: {log_path}")

        stats = read_json(stats_path)
        if not _is_json_object(stats):
            raise ValueError(f"event stats must be a JSON object: {stats_path}")
        stats_with_log = dict(stats)
        stats_with_log["quest_answer_log"] = _read_answer_log(log_path)
        anonymized_stats = anonymize_stats(stats_with_log)
        anonymized_log = cast(
            list[QuestAnswerLogRow], anonymized_stats.pop("quest_answer_log", [])
        )

        write_stats(anonymized_stats, anonymized_output_root, event_id, activity_id)
        write_report(
            render_report(anonymized_stats, config, activity),
            anonymized_output_root,
            event_id,
            activity_id,
        )
        write_quest_answer_log(
            anonymized_log,
            anonymized_output_root,
            event_id,
            activity_id,
        )


def _series_stats_paths(entries: list[EventConfig], output_root: Path) -> list[Path]:
    paths = [
        _activity_stats_path(output_root, config, activity)
        for _, config in entries
        for activity in config["activities"]
    ]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "cannot aggregate before all source reports exist: "
            + ", ".join(str(path) for path in missing)
        )
    return paths


def _generate_non_anonymized_aggregates(
    series_groups: dict[str, list[EventConfig]],
    full_output_root: Path,
    configs: list[EventConfig],
) -> list[str]:
    """Generate non-anonymized series aggregates and one all-events aggregate."""
    aggregate_ids: list[str] = []
    for series, entries in series_groups.items():
        if len(entries) < 2:
            continue

        title = f"{series.upper()} Aggregate Contribution Report"
        _write_non_anonymized_aggregate(
            entries,
            full_output_root,
            report_id=series,
            title=title,
        )
        aggregate_ids.append(series)
        print(f"Non-anonymized {series.upper()} aggregate written.")

    if configs:
        _write_non_anonymized_aggregate(
            configs,
            full_output_root,
            report_id="all",
            title="All Events Aggregate Contribution Report",
        )
        aggregate_ids.append("all")
        print("Non-anonymized all-events aggregate written.")
    return aggregate_ids


def _write_non_anonymized_aggregate(
    entries: list[EventConfig],
    full_output_root: Path,
    *,
    report_id: str,
    title: str,
) -> None:
    """Aggregate full source stats and write one report."""
    stats = aggregate_reports(
        _series_stats_paths(entries, full_output_root),
        title=title,
    )
    html = render_aggregate_report(stats)
    write_aggregate_report(
        stats,
        html,
        full_output_root / "events",
        report_id,
    )


def _render_anonymized_aggregates(
    aggregate_ids: list[str],
    full_output_root: Path,
    anonymized_output_root: Path,
) -> None:
    """Anonymize each full aggregate and write it to the anonymized root."""
    for aggregate_id in aggregate_ids:
        stats_path = (
            full_output_root / "events" / "aggregates" / aggregate_id / "stats.json"
        )
        stats = read_json(stats_path)
        if not _is_json_object(stats):
            raise ValueError(f"aggregate stats must be a JSON object: {stats_path}")
        anonymized_stats = anonymize_stats(stats)
        html = render_aggregate_report(anonymized_stats)
        write_aggregate_report(
            anonymized_stats,
            html,
            anonymized_output_root / "events",
            aggregate_id,
        )
        print(f"Anonymized {aggregate_id.upper()} aggregate written.")


def main(argv: list[str] | None = None) -> int:
    """Generate all configured event reports and matching aggregates."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate full and anonymized reports for every configured event, "
            "including quest-answer logs, series aggregates, and an all-events "
            "aggregate."
        )
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse event reports and logs that are already complete.",
    )
    args = parser.parse_args(argv)

    config_root = ROOT / "configs" / "events"
    version_root = ROOT / "local-output" / f"v{_project_version()}"
    full_output_root = version_root / "full"
    anonymized_output_root = version_root / "anonymized"

    try:
        configs = _discover_event_configs(config_root)
        print(f"Discovered {len(configs)} event configs under {config_root}.")

        for config_path, config in configs:
            if args.resume and _event_outputs_complete(config, full_output_root):
                print(f"Reusing completed full report for {config['id']}.")
                continue
            print(f"Generating full report for {config['id']} from {config_path}.")
            status = run_cli(
                [
                    "event",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(full_output_root),
                    "--quest-answer-log",
                ]
            )
            if status != 0:
                return status

        series_groups = _group_event_series(configs)
        aggregate_ids = _generate_non_anonymized_aggregates(
            series_groups,
            full_output_root,
            configs,
        )

        for _, config in configs:
            _render_anonymized_event(
                config,
                full_output_root,
                anonymized_output_root,
            )
            print(f"Anonymized reports and quest logs written for {config['id']}.")

        _render_anonymized_aggregates(
            aggregate_ids,
            full_output_root,
            anonymized_output_root,
        )
    except (OSError, ValueError, KeyError, csv.Error, tomllib.TOMLDecodeError) as exc:
        print(f"error: report generation failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Generated {len(configs)} event configs, "
        f"{len(aggregate_ids)} aggregates, and anonymized copies."
    )
    print(f"Full reports: {full_output_root}")
    print(f"Anonymized reports: {anonymized_output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
