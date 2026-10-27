"""Combine existing non-anonymized per-activity report statistics."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeGuard

from mm.common.io import read_json, require_safe_path_component, write_json, write_text

_ANONYMIZED_USER = re.compile(r"Participant \d+")


def _is_json_object(value: Any) -> TypeGuard[dict[str, Any]]:
    """Return whether *value* is a JSON object with string keys."""
    return isinstance(value, dict)


def _is_json_array(value: Any) -> TypeGuard[list[Any]]:
    """Return whether *value* is a JSON array."""
    return isinstance(value, list)


def _resolve_stats_path(report_path: str | Path) -> Path:
    """Resolve a report directory or stats file to its stats.json path."""
    path = Path(report_path)
    stats_path = path / "stats.json" if path.is_dir() else path
    if not stats_path.is_file():
        raise FileNotFoundError(f"Report stats not found: {stats_path}")
    return stats_path.resolve()


def _read_report_stats(stats_path: Path) -> dict[str, Any]:
    """Read and validate the top-level shape of one report's stats file."""
    try:
        stats = read_json(stats_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read report stats {stats_path}: {exc}") from exc
    if not _is_json_object(stats):
        raise ValueError(f"{stats_path}: report stats must be a JSON object")
    return stats


def _usernames_in_report(stats: dict[str, Any]) -> set[str]:
    """Collect structured identities for anonymization checks."""
    usernames: set[str] = set()
    for field in ("contributions_by_user", "contributors_breakdown"):
        entries = stats.get(field)
        if _is_json_array(entries):
            for entry in entries:
                if _is_json_object(entry):
                    user = entry.get("user")
                    if isinstance(user, str) and user:
                        usernames.add(user)

    markers = stats.get("markers")
    if _is_json_array(markers):
        for marker in markers:
            if not _is_json_object(marker):
                continue
            user = marker.get("user")
            if isinstance(user, str) and user:
                usernames.add(user)
            versions = marker.get("versions")
            if _is_json_array(versions):
                for version in versions:
                    if _is_json_object(version):
                        version_user = version.get("user")
                        if isinstance(version_user, str) and version_user:
                            usernames.add(version_user)
    return usernames


def _reject_anonymized_report(stats: dict[str, Any], stats_path: Path) -> None:
    """Reject reports whose identities cannot be matched across events."""
    if stats.get("anonymized") is True:
        raise ValueError(
            f"{stats_path}: anonymized reports cannot be aggregated; "
            "generate the per-event report without --anonymize"
        )

    usernames = _usernames_in_report(stats)
    if usernames and all(_ANONYMIZED_USER.fullmatch(user) for user in usernames):
        raise ValueError(
            f"{stats_path}: participant labels indicate an anonymized report; "
            "generate the per-event report without --anonymize"
        )


def _read_count(value: Any, field: str, stats_path: Path) -> int:
    """Validate a non-negative integer metric from a report."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{stats_path}: {field} must be a non-negative integer")
    return value


def _read_list(
    stats: dict[str, Any],
    field: str,
    stats_path: Path,
) -> list[Any]:
    """Read a report list field, treating an omitted optional field as empty."""
    value = stats.get(field, [])
    if not _is_json_array(value):
        raise ValueError(f"{stats_path}: {field} must be a list")
    return value


def _read_user_contributions(
    stats: dict[str, Any],
    stats_path: Path,
) -> list[dict[str, Any]]:
    """Read current per-user totals or recover them from legacy marker history."""
    if "contributions_by_user" not in stats:
        return _derive_user_contributions(stats, stats_path)

    contributions: list[dict[str, Any]] = []
    seen_users: set[str] = set()
    for index, entry in enumerate(
        _read_list(stats, "contributions_by_user", stats_path)
    ):
        if not _is_json_object(entry):
            raise ValueError(
                f"{stats_path}: contributions_by_user[{index}] must be an object"
            )
        user = entry.get("user")
        if not isinstance(user, str) or not user:
            raise ValueError(
                f"{stats_path}: contributions_by_user[{index}].user must be a "
                "non-empty string"
            )
        if user in seen_users:
            raise ValueError(f"{stats_path}: duplicate contributor {user!r}")
        seen_users.add(user)
        contributions.append(
            {
                "user": user,
                "quest_answer_count": _read_count(
                    entry.get("quest_answer_count"),
                    f"contributions_by_user[{index}].quest_answer_count",
                    stats_path,
                ),
                "note_count": _read_count(
                    entry.get("note_count"),
                    f"contributions_by_user[{index}].note_count",
                    stats_path,
                ),
            }
        )
    return contributions


def _derive_user_contributions(
    stats: dict[str, Any],
    stats_path: Path,
) -> list[dict[str, Any]]:
    """Recover contributor counts from marker histories in older reports."""
    quest_changesets: dict[str, set[str]] = {}
    notes_by_user: Counter[str] = Counter()
    usernames: set[str] = set()

    for marker_index, marker in enumerate(_read_list(stats, "markers", stats_path)):
        if not _is_json_object(marker):
            raise ValueError(f"{stats_path}: markers[{marker_index}] must be an object")

        marker_user = marker.get("user")
        if marker_user is not None and not isinstance(marker_user, str):
            raise ValueError(
                f"{stats_path}: markers[{marker_index}].user must be a string"
            )
        if marker_user:
            usernames.add(marker_user)

        if marker.get("kind") == "note":
            if marker_user:
                notes_by_user[marker_user] += 1
            continue

        versions = marker.get("versions", [])
        if not _is_json_array(versions):
            raise ValueError(
                f"{stats_path}: markers[{marker_index}].versions must be a list"
            )
        if not versions and marker_user and marker.get("changeset") is not None:
            quest_changesets.setdefault(marker_user, set()).add(
                str(marker["changeset"])
            )

        for version_index, version in enumerate(versions):
            if not _is_json_object(version):
                raise ValueError(
                    f"{stats_path}: markers[{marker_index}].versions"
                    f"[{version_index}] must be an object"
                )
            user = version.get("user")
            if user is not None and not isinstance(user, str):
                raise ValueError(
                    f"{stats_path}: markers[{marker_index}].versions"
                    f"[{version_index}].user must be a string"
                )
            changeset = version.get("changeset")
            if user:
                usernames.add(user)
                if changeset is not None:
                    quest_changesets.setdefault(user, set()).add(str(changeset))

    for index, contributor in enumerate(
        _read_list(stats, "contributors_breakdown", stats_path)
    ):
        if not _is_json_object(contributor):
            raise ValueError(
                f"{stats_path}: contributors_breakdown[{index}] must be an object"
            )
        user = contributor.get("user")
        if user is not None and not isinstance(user, str):
            raise ValueError(
                f"{stats_path}: contributors_breakdown[{index}].user must be a string"
            )
        if user:
            usernames.add(user)

    changeset_count = _read_count(
        stats.get("changeset_count", 0), "changeset_count", stats_path
    )
    if changeset_count and not quest_changesets:
        raise ValueError(
            f"{stats_path}: contributor changeset history is missing; "
            "regenerate this report with the current version before aggregating"
        )
    if not usernames and stats.get("contributor_count", 0):
        raise ValueError(
            f"{stats_path}: contributor identities are missing; "
            "regenerate this report with the current version before aggregating"
        )

    return [
        {
            "user": user,
            "quest_answer_count": len(quest_changesets.get(user, set())),
            "note_count": notes_by_user[user],
        }
        for user in sorted(usernames, key=lambda name: (name.casefold(), name))
    ]


def _parse_utc_timestamp(value: Any, field: str, stats_path: Path) -> datetime:
    """Parse an ISO timestamp and require an explicit UTC offset."""
    if not isinstance(value, str):
        raise ValueError(f"{stats_path}: {field} must be a UTC timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{stats_path}: invalid {field}: {value!r}") from exc
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError(f"{stats_path}: {field} must use the UTC time zone")
    return timestamp


def _format_date(timestamp: datetime) -> str:
    """Format a UTC timestamp as a readable month-day-year label."""
    return f"{timestamp:%B} {timestamp.day}, {timestamp:%Y}"


def _format_period(start: datetime, end: datetime) -> str:
    """Format a report window as one date or a pair of dates."""
    start_date = _format_date(start)
    end_date = _format_date(end)
    return start_date if start.date() == end.date() else f"{start_date} – {end_date}"


def _fallback_event_id(stats_path: Path) -> str:
    """Infer a legacy report's event id from its standard output path."""
    if (
        stats_path.parent.parent.parent.name == "events"
        and stats_path.parent.parent.name
    ):
        return stats_path.parent.parent.name
    return stats_path.parent.name


def _string_field(
    stats: dict[str, Any],
    field: str,
    fallback: str,
    stats_path: Path,
) -> str:
    """Read an optional non-empty string field or return its fallback."""
    value = stats.get(field)
    if value is None or value == "":
        return fallback
    if not isinstance(value, str):
        raise ValueError(f"{stats_path}: {field} must be a string")
    return value.strip() or fallback


def aggregate_reports(
    report_paths: list[str | Path],
    *,
    title: str = "Aggregate Contribution Report",
) -> dict[str, Any]:
    """Merge reports by exact username and sum their activity metrics."""
    if not report_paths:
        raise ValueError("at least one report path is required")
    if not title.strip():
        raise ValueError("aggregate report title cannot be empty")

    seen_paths: set[str] = set()
    seen_reports: set[tuple[str, str]] = set()
    events: list[dict[str, Any]] = []
    all_markers: list[dict[str, Any]] = []
    contributor_totals: dict[str, dict[str, int]] = {}
    category_counts: Counter[str] = Counter()
    category_photo_counts: Counter[str] = Counter()
    feature_counts: Counter[str] = Counter()
    total_quest_answers = 0
    total_reported_changesets = 0
    total_notes = 0
    total_unattributed_notes = 0
    legacy_quest_count_mismatch_event_count = 0

    for report_path in report_paths:
        stats_path = _resolve_stats_path(report_path)
        canonical_path = str(stats_path).casefold()
        if canonical_path in seen_paths:
            raise ValueError(f"duplicate report path: {stats_path}")
        seen_paths.add(canonical_path)

        stats = _read_report_stats(stats_path)
        _reject_anonymized_report(stats, stats_path)
        if stats.get("report_type") == "aggregate":
            raise ValueError(
                f"{stats_path}: aggregate reports cannot be source reports"
            )
        if stats.get("source_type") != "workspace":
            raise ValueError(f"{stats_path}: only workspace reports can be aggregated")

        event_id = _string_field(
            stats, "event_id", _fallback_event_id(stats_path), stats_path
        )
        activity_id = _string_field(
            stats, "activity_id", stats_path.parent.name, stats_path
        )
        report_identity = (event_id, activity_id)
        if report_identity in seen_reports:
            raise ValueError(
                f"duplicate report for event {event_id!r}, activity {activity_id!r}"
            )
        seen_reports.add(report_identity)

        event_name = _string_field(stats, "event_name", event_id, stats_path)
        activity_label = _string_field(stats, "activity_label", activity_id, stats_path)
        start = _parse_utc_timestamp(
            stats.get("window_start"), "window_start", stats_path
        )
        end = _parse_utc_timestamp(stats.get("window_end"), "window_end", stats_path)
        if end < start:
            raise ValueError(f"{stats_path}: window_end must not precede window_start")

        reported_changesets = _read_count(
            stats.get("changeset_count"), "changeset_count", stats_path
        )
        notes = _read_count(stats.get("note_count"), "note_count", stats_path)
        legacy_contributions = "contributions_by_user" not in stats
        user_contributions = _read_user_contributions(stats, stats_path)
        attributed_quest_answers = sum(
            item["quest_answer_count"] for item in user_contributions
        )
        quest_answers = reported_changesets
        if attributed_quest_answers != reported_changesets:
            if legacy_contributions and attributed_quest_answers > reported_changesets:
                quest_answers = attributed_quest_answers
                legacy_quest_count_mismatch_event_count += 1
            else:
                raise ValueError(
                    f"{stats_path}: contributor quest totals do not match "
                    "changeset_count; regenerate this report with the current version"
                )
        attributed_notes = sum(item["note_count"] for item in user_contributions)
        if attributed_notes > notes:
            raise ValueError(
                f"{stats_path}: contributor note totals exceed note_count"
            )
        unattributed_notes = notes - attributed_notes
        events.append(
            {
                "event_id": event_id,
                "event_name": event_name,
                "activity_id": activity_id,
                "activity_label": activity_label,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "period_label": _format_period(start, end),
                "quest_answer_count": quest_answers,
                "reported_changeset_count": reported_changesets,
                "note_count": notes,
                "unattributed_note_count": unattributed_notes,
                "contribution_count": quest_answers + notes,
                "contributor_count": len(user_contributions),
            }
        )
        total_quest_answers += quest_answers
        total_reported_changesets += reported_changesets
        total_notes += notes
        total_unattributed_notes += unattributed_notes

        for contribution in user_contributions:
            user = contribution["user"]
            totals = contributor_totals.setdefault(
                user,
                {"quest_answer_count": 0, "note_count": 0},
            )
            totals["quest_answer_count"] += contribution["quest_answer_count"]
            totals["note_count"] += contribution["note_count"]

        for index, category in enumerate(
            _read_list(stats, "quest_type_breakdown", stats_path)
        ):
            if not _is_json_object(category):
                raise ValueError(
                    f"{stats_path}: quest_type_breakdown[{index}] must be an object"
                )
            name = category.get("category", "")
            if not isinstance(name, str):
                raise ValueError(
                    f"{stats_path}: quest_type_breakdown[{index}].category "
                    "must be a string"
                )
            label = name or "(unknown)"
            category_counts[label] += _read_count(
                category.get("count"),
                f"quest_type_breakdown[{index}].count",
                stats_path,
            )
            category_photo_counts[label] += _read_count(
                category.get("photo_count", 0),
                f"quest_type_breakdown[{index}].photo_count",
                stats_path,
            )

        for index, feature in enumerate(
            _read_list(stats, "features_created", stats_path)
        ):
            if not _is_json_object(feature):
                raise ValueError(
                    f"{stats_path}: features_created[{index}] must be an object"
                )
            feature_type = feature.get("feature_type")
            if not isinstance(feature_type, str) or not feature_type:
                raise ValueError(
                    f"{stats_path}: features_created[{index}].feature_type "
                    "must be a non-empty string"
                )
            feature_counts[feature_type] += _read_count(
                feature.get("count"),
                f"features_created[{index}].count",
                stats_path,
            )

        for index, marker in enumerate(_read_list(stats, "markers", stats_path)):
            if not _is_json_object(marker):
                raise ValueError(f"{stats_path}: markers[{index}] must be an object")
            aggregate_marker = dict(marker)
            aggregate_marker["event_id"] = event_id
            aggregate_marker["event_name"] = event_name
            aggregate_marker["activity_label"] = activity_label
            all_markers.append(aggregate_marker)

    events.sort(
        key=lambda event: (
            event["window_start"],
            event["event_name"].casefold(),
            event["activity_label"].casefold(),
        )
    )
    contributors: list[dict[str, str | int]] = [
        {
            "user": user,
            "quest_answer_count": totals["quest_answer_count"],
            "note_count": totals["note_count"],
            "contribution_count": (totals["quest_answer_count"] + totals["note_count"]),
        }
        for user, totals in sorted(
            contributor_totals.items(),
            key=lambda item: (
                -item[1]["quest_answer_count"],
                -item[1]["note_count"],
                item[0].casefold(),
                item[0],
            ),
        )
    ]
    quest_type_breakdown: list[dict[str, str | int]] = [
        {
            "category": category,
            "count": count,
            "photo_count": category_photo_counts[category],
        }
        for category, count in sorted(
            category_counts.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]
    features_created: list[dict[str, str | int]] = [
        {"feature_type": feature_type, "count": count}
        for feature_type, count in sorted(
            feature_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    starts = [datetime.fromisoformat(event["window_start"]) for event in events]
    ends = [datetime.fromisoformat(event["window_end"]) for event in events]
    start = min(starts)
    end = max(ends)
    event_ids = {event["event_id"] for event in events}

    return {
        "report_type": "aggregate",
        "source_type": "workspace",
        "title": title.strip(),
        "period_label": _format_period(start, end),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "event_count": len(event_ids),
        "report_count": len(events),
        "contributor_count": len(contributors),
        "quest_answer_count": total_quest_answers,
        "changeset_count": total_quest_answers,
        "reported_changeset_count": total_reported_changesets,
        "legacy_quest_count_mismatch_event_count": (
            legacy_quest_count_mismatch_event_count
        ),
        "note_count": total_notes,
        "unattributed_note_count": total_unattributed_notes,
        "new_feature_count": sum(feature_counts.values()),
        "events": events,
        "contributions_by_user": contributors,
        "quest_type_breakdown": quest_type_breakdown,
        "features_created": features_created,
        "markers": all_markers,
        "max_event_contribution_count": max(
            (event["contribution_count"] for event in events),
            default=0,
        ),
    }


def write_aggregate_report(
    stats: dict[str, Any],
    html: str,
    output_dir: Path,
    report_id: str,
) -> Path:
    """Write aggregate stats and HTML beneath ``aggregates/<report_id>``."""
    safe_report_id = require_safe_path_component(report_id, "report_id")
    report_dir = output_dir / "aggregates" / safe_report_id
    write_json(report_dir / "stats.json", stats)
    write_text(report_dir / "index.html", html)
    return report_dir / "index.html"
