"""End-to-end orchestration for one Mapping Momentum workspace activity."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mm.config.schema import ENV_CREDENTIAL_VAR
from mm.outputs.html_report import render_report, write_report
from mm.outputs.json_stats import build_stats, write_stats
from mm.quests.loader import load_quest_definition
from mm.sources.base import SourceResult
from mm.sources.workspace import (
    build_version_histories,
    enrich_elements,
    fetch_bbox,
    fetch_changeset_xml,
    fetch_changesets,
    fetch_notes,
    fetch_osm_xml,
    filter_actions_by_time,
    parse_notes,
    parse_osm_xml,
    parse_osmchange,
    resolve_way_geometry,
)


def parse_window(activity: dict[str, Any]) -> tuple[datetime, datetime]:
    """Parse an activity's UTC time window into timezone-aware datetimes."""

    def parse(value: str) -> datetime:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.utcoffset() != timedelta(0):
            raise ValueError(f"activity timestamp is not UTC: {value!r}")
        return dt

    window = activity["time_window"]
    return parse(window["start"]), parse(window["end"])


def run_activity(
    config: dict[str, Any],
    activity: dict[str, Any],
    *,
    output_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch, enrich, measure, and optionally write one activity report.

    The quest definition is deliberately loaded only from the event directory;
    normal report generation never reaches out to the quest repository.
    """
    if activity.get("type") != "workspace":
        raise ValueError(f"unsupported activity type: {activity.get('type')!r}")

    event_dir = Path(config["_event_dir"])
    activity_id = activity["id"]
    cache_candidates = (
        event_dir / "quest-definitions" / f"{activity_id}.json",
        event_dir / "quest-definition.json",
    )
    quest_cache = next((path for path in cache_candidates if path.is_file()), None)
    if quest_cache is None:
        raise FileNotFoundError(
            f"No quest definition cache found for activity {activity_id!r}; "
            f"expected {cache_candidates[0]}"
        )
    quest_def = load_quest_definition(quest_cache)
    env_var = ENV_CREDENTIAL_VAR[activity["environment"]]
    api_key = os.environ.get(env_var)
    if not api_key:
        raise ValueError(f"required environment variable {env_var!r} is not set")

    window_start, window_end = parse_window(activity)
    env = activity["environment"]
    workspace_id = activity["workspace_id"]
    bbox = fetch_bbox(env, workspace_id, api_key)
    snapshot = parse_osm_xml(fetch_osm_xml(env, workspace_id, bbox, api_key))
    metadata = fetch_changesets(env, workspace_id, window_start, window_end, api_key)
    actions = []
    for item in metadata:
        if "id" in item:
            changeset_xml = fetch_changeset_xml(
                env, workspace_id, int(item["id"]), api_key
            )
            actions.extend(
                filter_actions_by_time(
                    parse_osmchange(changeset_xml), window_start, window_end
                )
            )
    histories = build_version_histories(actions, quest_def=quest_def)

    # Use the complete current snapshot for geometry and display state. The
    # event window is applied to individual changeset actions above; filtering
    # the snapshot by its current timestamp would omit elements edited again
    # after the event.
    elements = enrich_elements(snapshot, histories, quest_def=quest_def)
    resolve_way_geometry(elements, coordinate_source=snapshot)
    elements.extend(
        parse_notes(fetch_notes(env, workspace_id, api_key), window_start, window_end)
    )
    elements.sort(key=lambda item: (item.get("type", ""), item.get("id", 0)))

    result = SourceResult(
        source_type="workspace",
        activity_id=activity_id,
        window_start=window_start,
        window_end=window_end,
        elements=elements,
    )
    stats = build_stats(
        result,
        quest_def=quest_def,
        showcase_photos=config.get("showcase_photos", []),
        event_dir=event_dir,
    )
    if not dry_run:
        event_id = config["id"]
        write_stats(stats, output_dir, event_id, activity["id"])
        write_report(
            render_report(stats, config, activity),
            output_dir,
            event_id,
            activity["id"],
        )
    return stats
