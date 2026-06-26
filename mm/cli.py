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

    Validates the config; the full pipeline (fetch → metrics → render) will be
    implemented in later slices.  For now, a successful load prints a summary
    and exits cleanly.
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

    event_id = config["id"]
    activity_ids = [a["id"] for a in config["activities"]]
    print(f"Loaded event {event_id!r} with activities: {activity_ids}")
    print("Pipeline not yet implemented — later slices pending.")
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
