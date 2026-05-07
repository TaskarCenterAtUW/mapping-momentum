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
        help="Generate a report for one event config.",
    )
    event_parser.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="Path to the event JSON config file.",
    )
    event_parser.add_argument(
        "--output-dir",
        default="local-output",
        metavar="PATH",
        help="Root directory for generated output (default: local-output/).",
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

    # Should be unreachable given subparsers.required = True, but be safe.
    parser.print_help()
    return 1


def _cmd_event(args: argparse.Namespace) -> int:
    """Handle the ``event`` subcommand.

    Validates the config; the full pipeline (fetch → metrics → render) will be
    implemented in Slice 2/3.  For now, a successful load prints a summary and
    exits cleanly so Slice 1 can be tested end-to-end.
    """
    from mm.config.loader import (
        ConfigError,
        load_event_config,
    )

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"error: config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        config = load_event_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    event_id = config["id"]
    activity_ids = [a["id"] for a in config["activities"]]
    print(f"Loaded event {event_id!r} with activities: {activity_ids}")
    print("Pipeline not yet implemented — Slice 2/3 pending.")
    return 0
