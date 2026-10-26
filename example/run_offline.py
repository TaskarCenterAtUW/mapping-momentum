"""Run a synthetic Mapping Momentum event without network access.

This exercises the same parsing, enrichment, metrics, stats, and HTML report
stages as the live pipeline, using the raw payloads stored beside an example
event configuration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mm.common.io import read_json  # noqa: E402
from mm.config.loader import load_event_config  # noqa: E402
from mm.outputs.anonymize import anonymize_stats  # noqa: E402
from mm.outputs.html_report import render_report, write_report  # noqa: E402
from mm.outputs.json_stats import build_stats, write_stats  # noqa: E402
from mm.pipeline import get_report_feature, parse_window  # noqa: E402
from mm.quests.loader import load_quest_definition  # noqa: E402
from mm.sources.base import SourceResult  # noqa: E402
from mm.sources.workspace import (  # noqa: E402
    build_version_histories,
    enrich_elements,
    filter_actions_by_time,
    parse_notes,
    parse_osm_xml,
    parse_osmchange,
    resolve_way_geometry,
)


def run_offline(
    event_dir: Path,
    output_dir: Path,
    *,
    anonymize: bool = False,
) -> tuple[Path, Path]:
    """Run one example, optionally anonymize names, and return output paths."""
    event_dir = event_dir.resolve()
    config_path = event_dir / "event.json"

    config = load_event_config(config_path)
    activity = config["activities"][0]

    quest_path = event_dir / "quest-definitions" / f"{activity['id']}.json"
    quest_def = load_quest_definition(quest_path)
    offline_dir = event_dir / "offline"
    snapshot = parse_osm_xml((offline_dir / "map.osm").read_bytes())

    actions: list[tuple[str, dict[str, Any]]] = []
    changeset_dir = offline_dir / "changesets"
    for path in sorted(changeset_dir.glob("*.osmchange")):
        actions.extend(parse_osmchange(path.read_bytes()))

    window_start, window_end = parse_window(activity)
    actions = filter_actions_by_time(actions, window_start, window_end)
    histories = build_version_histories(actions, quest_def=quest_def)
    elements = enrich_elements(snapshot, histories, quest_def=quest_def)
    resolve_way_geometry(elements, coordinate_source=snapshot)

    notes_path = offline_dir / "notes.json"
    elements.extend(
        parse_notes(
            read_json(notes_path),
            window_start=window_start,
            window_end=window_end,
        )
    )
    elements.sort(key=lambda item: (item.get("type", ""), item.get("id", 0)))

    result = SourceResult(
        source_type="workspace",
        activity_id=activity["id"],
        window_start=window_start,
        window_end=window_end,
        elements=elements,
    )
    stats = build_stats(
        result,
        quest_def=quest_def,
        showcase_photos=config.get("showcase_photos", []),
        pictures=get_report_feature(config, "pictures", []),
        quotes=get_report_feature(config, "quotes", []),
        slideshow_url=get_report_feature(config, "slideshow_url", None),
        video_url=get_report_feature(config, "video_url", None),
        event_dir=event_dir,
    )
    if anonymize:
        stats = anonymize_stats(stats)

    stats_path = write_stats(stats, output_dir, config["id"], activity["id"])
    report_path = write_report(
        render_report(stats, config, activity),
        output_dir,
        config["id"],
        activity["id"],
    )
    return stats_path, report_path


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run an example, and print generated output paths."""
    parser = argparse.ArgumentParser(
        description="Run a synthetic Mapping Momentum event offline."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Example event directory containing event.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("local-output"),
        help="Output directory (default: local-output/).",
    )
    parser.add_argument(
        "-a",
        "--anonymize",
        action="store_true",
        help="Replace participant names with anonymous labels in report output.",
    )
    args = parser.parse_args(argv)

    stats_path, report_path = run_offline(
        args.config,
        args.output_dir,
        anonymize=args.anonymize,
    )
    print(f"Stats written to {stats_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
