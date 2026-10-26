"""
mm.cli — subcommand definitions for the Mapping Momentum CLI.

Entry point: the ``mapping-momentum`` console script delegates to ``run_cli``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

from mm.config.schema import SLUG_PATTERN
from mm.sources.workspace import authenticate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapping-momentum",
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

    capture_parser = subparsers.add_parser(
        "capture",
        help="Capture raw Workspace responses for an offline fixture.",
    )
    capture_parser.add_argument("--config", required=True, metavar="PATH")
    capture_parser.add_argument("--activity-id", required=True, metavar="ID")
    capture_parser.add_argument("--fixture-name", required=True, metavar="NAME")
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
    event_parser.add_argument(
        "-a",
        "--anonymize",
        action="store_true",
        help="Replace participant names with anonymous labels in report output.",
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
    if args.command == "capture":
        return _cmd_capture(args)

    # Should be unreachable given subparsers.required = True, but be safe.
    parser.print_help()
    return 1


def _get_access_token(environment: str) -> str:
    """Authenticate from a complete environment pair or secure prompts."""
    username_var = f"MM_TDEI_USERNAME_{environment.upper()}"
    password_var = f"MM_TDEI_PASSWORD_{environment.upper()}"
    has_username = username_var in os.environ
    has_password = password_var in os.environ

    if has_username != has_password:
        raise ValueError(
            f"{username_var} and {password_var} must be set together."
        )

    if has_username:
        username = os.environ[username_var].strip()
        password = os.environ[password_var]
        if not username:
            raise ValueError(f"Environment variable {username_var} cannot be empty.")
        if not password:
            raise ValueError(f"Environment variable {password_var} cannot be empty.")
    else:
        if not (sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()):
            raise ValueError(
                "TDEI credentials require an interactive terminal or both "
                f"{username_var} and {password_var} environment variables."
            )

        try:
            username = input(f"TDEI {environment} username: ").strip()
        except EOFError as exc:
            raise ValueError("No TDEI username was entered.") from exc
        if not username:
            raise ValueError("TDEI username cannot be empty.")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass(f"TDEI {environment} password: ")
        except getpass.GetPassWarning as exc:
            raise ValueError(
                "Cannot read the TDEI password without echo; "
                "use an interactive terminal."
            ) from exc
        except EOFError as exc:
            raise ValueError("No TDEI password was entered.") from exc
        if not password:
            raise ValueError("TDEI password cannot be empty.")

    return authenticate(environment, username, password)


def _cmd_event(args: argparse.Namespace) -> int:
    """Handle the ``event`` subcommand.

    When ``--render-from-stats`` is given, renders index.html from an existing
    stats.json without any network calls (useful for testing the template).

    Otherwise runs the complete fetch → enrich → metrics → render pipeline.
    """
    from mm.config.loader import ConfigError, load_event_config

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"error: config path not found: {config_path}", file=sys.stderr)
        return 1

    try:
        config = load_event_config(config_path)
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    event_id: str = config["id"]
    output_dir = Path(getattr(args, "output_dir", "local-output"))

    # --render-from-stats: re-render HTML from an existing stats.json
    render_from = getattr(args, "render_from_stats", None)
    anonymize = bool(getattr(args, "anonymize", False))
    if render_from:
        return _render_from_stats(
            config,
            Path(render_from),
            output_dir,
            event_id,
            anonymize=anonymize,
        )

    from mm.pipeline import run_activity

    try:
        access_tokens: dict[str, str] = {}
        for activity in config["activities"]:
            environment = activity["environment"]
            if environment not in access_tokens:
                access_tokens[environment] = _get_access_token(environment)
            stats = run_activity(
                config,
                activity,
                output_dir=output_dir,
                access_token=access_tokens[environment],
                dry_run=bool(getattr(args, "dry_run", False)),
                anonymize=anonymize,
            )
            if getattr(args, "dry_run", False):
                print(json.dumps(stats, indent=2, ensure_ascii=False))
            else:
                print(
                    "Report written to "
                    f"{output_dir / 'events' / event_id / activity['id']}"
                )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    """Capture raw map, changeset, and notes payloads for an offline fixture."""
    from mm.common.io import write_json
    from mm.config.loader import ConfigError, load_event_config
    from mm.pipeline import parse_window
    from mm.sources.workspace import (
        fetch_bbox,
        fetch_changeset_xml,
        fetch_changesets,
        fetch_notes,
        fetch_osm_xml,
    )

    try:
        config = load_event_config(Path(args.config))
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    activity = next(
        (item for item in config["activities"] if item["id"] == args.activity_id),
        None,
    )
    if activity is None:
        print(f"error: activity not found: {args.activity_id}", file=sys.stderr)
        return 1
    env = activity["environment"]

    start, end = parse_window(activity)
    workspace_id = activity["workspace_id"]
    if not isinstance(args.fixture_name, str) or not SLUG_PATTERN.fullmatch(
        args.fixture_name
    ):
        print(
            "error: fixture name must contain only lowercase letters, digits, "
            "and hyphens",
            file=sys.stderr,
        )
        return 1

    fixture_root = Path("tests/golden/fixtures").resolve()
    fixture_root.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = (fixture_root / args.fixture_name).resolve()
    if fixture_dir.parent != fixture_root:
        print("error: fixture path escapes the fixture directory", file=sys.stderr)
        return 1

    try:
        access_token = _get_access_token(env)
        with tempfile.TemporaryDirectory(dir=fixture_root.parent) as temp_name:
            staging_dir = Path(temp_name) / args.fixture_name
            staging_dir.mkdir()
            map_bytes = fetch_osm_xml(
                env,
                workspace_id,
                fetch_bbox(env, workspace_id, access_token),
                access_token,
            )
            (staging_dir / "map.osm").write_bytes(map_bytes)
            changesets = fetch_changesets(env, workspace_id, start, end, access_token)
            write_json(staging_dir / "changesets.json", changesets)
            for item in changesets:
                if "id" in item:
                    (staging_dir / f"changeset-{item['id']}.osmchange").write_bytes(
                        fetch_changeset_xml(
                            env, workspace_id, int(item["id"]), access_token
                        )
                    )
            write_json(
                staging_dir / "notes.json",
                fetch_notes(env, workspace_id, access_token),
            )
            if fixture_dir.exists():
                shutil.rmtree(fixture_dir)
            fixture_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging_dir), str(fixture_dir))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: fixture capture failed: {exc}", file=sys.stderr)
        return 1

    print(f"Fixture captured to {fixture_dir}")
    return 0


def _render_from_stats(
    config: dict,
    stats_path: Path,
    output_dir: Path,
    event_id: str,
    *,
    anonymize: bool = False,
) -> int:
    """Render index.html from an existing stats.json file.

    Reads the stats.json at *stats_path*, finds the matching activity config,
    and renders the HTML report to the standard output path.
    """
    from mm.common.io import read_json
    from mm.outputs.html_report import render_report, write_report
    from mm.outputs.json_stats import write_stats

    if not stats_path.exists():
        print(f"error: stats.json not found: {stats_path}", file=sys.stderr)
        return 1

    try:
        stats: dict = read_json(stats_path)
    except Exception as exc:
        print(f"error: could not read {stats_path}: {exc}", file=sys.stderr)
        return 1
    if anonymize:
        from mm.outputs.anonymize import anonymize_stats

        stats = anonymize_stats(stats)

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
    if anonymize:
        write_stats(stats, output_dir, event_id, activity_id or "activity")
    dest = write_report(html, output_dir, event_id, activity_id or "activity")
    print(f"Report written to {dest}")
    return 0


def _cmd_capture_quests(args: argparse.Namespace) -> int:
    """Handle the ``capture-quests`` subcommand.

    For each workspace activity in the event config that has a
    ``quest_definition_url``, fetches the upstream quest definition and
    writes it to ``<event-dir>/quest-definitions/<activity-id>.json``. Stamps the
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
    except (ConfigError, OSError) as exc:
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
        dest = event_dir / "quest-definitions" / f"{act_id}.json"

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
