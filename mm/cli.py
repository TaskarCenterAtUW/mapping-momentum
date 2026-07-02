"""
mm.cli — subcommand definitions for the Mapping Momentum CLI.

Entry point: generate-stats.py (at repo root) delegates to run_cli().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-stats",
        description="Generate statistics and HTML reports for mapping events.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # --- event subcommand ---
    event_parser = subparsers.add_parser(
        "event",
        help="Generate a report for one event (directory or event.json).",
    )
    event_parser.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="Path to the event directory or its event.json file.",
    )
    event_parser.add_argument(
        "--output-dir",
        default="local-output",
        metavar="PATH",
        help="Root directory for generated output (default: local-output/).",
    )
    event_parser.add_argument(
        "--render-from-stats",
        metavar="PATH",
        help=(
            "Render index.html from an existing stats.json without fetching "
            "live data.  Useful for re-rendering after template changes."
        ),
    )
    event_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats to stdout without writing any files.",
    )

    # --- capture-quests subcommand ---
    cq_parser = subparsers.add_parser(
        "capture-quests",
        help=(
            "Fetch and cache quest definitions for all workspace activities "
            "in an event config.  The only networked path for quest definitions."
        ),
    )
    cq_parser.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="Path to the event directory or its event.json file.",
    )

    return parser


def run_cli(argv: list[str] | None = None) -> int:
    """Parse *argv* and dispatch the requested subcommand.

    Returns the process exit code (0 = success, non-zero = failure).
    This function is imported and called by generate-stats.py.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "event":
        return _cmd_event(args)
    if args.command == "capture-quests":
        return _cmd_capture_quests(args)

    # Should be unreachable given subparsers.required = True, but be safe.
    parser.print_help()
    return 1


def _cmd_event(args: argparse.Namespace) -> int:
    """Handle the ``event`` subcommand.

    When ``--render-from-stats`` is given, renders index.html from an existing
    stats.json without any network calls (useful for testing the template).

    Otherwise the full pipeline would run (fetch → enrich → metrics → render),
    but that path requires confirmed live API endpoints and is gated behind
    Slice F.  For now, a config-only validation run prints a summary.
    """
    from mm.config.loader import ConfigError, load_event_config

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: config path not found: {config_path}", file=sys.stderr)
        return 1

    try:
        config = load_event_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    event_id: str = config["id"]
    output_dir = Path(getattr(args, "output_dir", "local-output"))

    # --render-from-stats: re-render HTML from an existing stats.json
    render_from = getattr(args, "render_from_stats", None)
    if render_from:
        return _render_from_stats(config, Path(render_from), output_dir, event_id)

    # Validate and summarise without fetching live data
    activity_ids = [a["id"] for a in config["activities"]]
    print(f"Loaded event {event_id!r} with activities: {activity_ids}")
    print("Live data fetch not yet wired (pending Slice F / confirmed endpoints).")
    return 0


def _render_from_stats(
    config: dict,
    stats_path: Path,
    output_dir: Path,
    event_id: str,
) -> int:
    """Render index.html from an existing stats.json file.

    Reads the stats.json at *stats_path*, finds the matching activity config,
    and renders the HTML report to the standard output path.
    """
    from mm.common.io import read_json
    from mm.outputs.html_report import render_report, write_report

    if not stats_path.exists():
        print(f"error: stats.json not found: {stats_path}", file=sys.stderr)
        return 1

    try:
        stats: dict = read_json(stats_path)
    except Exception as exc:
        print(f"error: could not read {stats_path}: {exc}", file=sys.stderr)
        return 1

    activity_id: str = stats.get("activity_id", "")
    # Find matching activity config
    activity = next(
        (a for a in config.get("activities", []) if a.get("id") == activity_id),
        None,
    )
    if activity is None:
        # Fall back to first activity if activity_id doesn't match
        activities = config.get("activities", [])
        activity = activities[0] if activities else {}

    html = render_report(stats, config, activity)
    dest = write_report(html, output_dir, event_id, activity_id or "activity")
    print(f"Report written to {dest}")
    return 0


def _cmd_capture_quests(args: argparse.Namespace) -> int:
    """Handle the ``capture-quests`` subcommand.

    For each workspace activity in the event config that has a
    ``quest_definition_url``, fetches the upstream quest definition and
    writes it to ``<event-dir>/quest-definition.json``.  Stamps the
    retrieval timestamp into ``event.json`` so cache freshness is
    recorded without a network round-trip.
    """
    from mm.config.loader import ConfigError, load_event_config
    from mm.quests.capture import capture_quest_definition, stamp_retrieval_date

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: config path not found: {config_path}", file=sys.stderr)
        return 1

    try:
        config = load_event_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    event_dir: Path = config["_event_dir"]
    event_json_path = event_dir / "event.json"
    fetched = 0

    for activity in config.get("activities", []):
        if activity.get("type") != "workspace":
            continue
        url: str = activity.get("quest_definition_url", "")
        if not url:
            continue
        act_id: str = activity["id"]
        dest = event_dir / "quest-definition.json"

        print(f"[{act_id}] fetching {url}")
        try:
            retrieval_date = capture_quest_definition(url, dest)
        except Exception as exc:
            print(
                f"error: failed to fetch quest definition for {act_id!r}: {exc}",
                file=sys.stderr,
            )
            return 1

        stamp_retrieval_date(event_json_path, act_id, retrieval_date)
        print(f"[{act_id}] written to {dest} (retrieved {retrieval_date})")
        fetched += 1

    if fetched == 0:
        print(
            "warning: no workspace activities with quest_definition_url found",
            file=sys.stderr,
        )
    return 0
