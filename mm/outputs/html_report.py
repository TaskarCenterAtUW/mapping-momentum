"""
mm.outputs.html_report — render the self-contained HTML report for one activity.

The report is rendered from a Jinja2 template (``templates/activity_report.html``)
with all event data inlined. MapLibre GL JS is the only runtime CDN dependency;
cards remain usable when the map script or tiles are unavailable.

Usage::

    from mm.outputs.html_report import render_report, write_report

    html = render_report(stats, config, activity)
    dest = write_report(html, output_dir, event_id, activity_id)
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections.abc import Mapping
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from mm.common.io import require_safe_path_component, write_text

# Prefer repository templates in a source checkout; installed distributions
# use the shared data installed under the interpreter prefix.
_INSTALLED_TEMPLATE_DIR = Path(sys.prefix) / "templates"
_SOURCE_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"
_DEFAULT_TEMPLATE_DIR = (
    _SOURCE_TEMPLATE_DIR
    if (_SOURCE_TEMPLATE_DIR / "activity_report.html").is_file()
    else _INSTALLED_TEMPLATE_DIR
)


def _application_version() -> str:
    """Return the installed project version, falling back to source metadata."""
    try:
        return distribution_version("mapping-momentum")
    except PackageNotFoundError:
        project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            project = tomllib.loads(project_file.read_text(encoding="utf-8"))
        except OSError, tomllib.TOMLDecodeError:
            return "unknown"
        version_value = project.get("project", {}).get("version")
        return version_value if isinstance(version_value, str) else "unknown"


_APP_VERSION = _application_version()


def _export_filename(value: str, *, suffix: str) -> str:
    """Build a filesystem-safe meaningful report download filename."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return f"{slug or 'mapping-momentum'}-{suffix}.html"


def _safe_json(data: Any) -> str:
    """Serialise *data* to JSON safe for inline embedding in ``<script>`` blocks.

    Python's ``json.dumps`` does not escape ``<``, ``>``, or ``&``, which can
    allow tag injection when arbitrary user data is embedded in a ``<script>``.
    This function escapes those characters to their Unicode counterparts so the
    JSON string cannot break out of a script context.
    """
    return (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _aggregate_series_name(stats: dict[str, Any], title: str) -> str:
    """Return the event-series label used in aggregate breadcrumbs."""
    for key in ("series_name", "event_series_name"):
        value = stats.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    events_value: object = stats.get("events")
    event_names: list[str] = []
    if isinstance(events_value, list):
        for event_value in cast(list[object], events_value):
            if not isinstance(event_value, dict):
                continue
            event = cast(Mapping[object, object], event_value)
            event_name = event.get("event_name")
            if isinstance(event_name, str) and event_name.strip():
                event_names.append(event_name.strip())

    prefixes: list[str] = [
        name.split(":", 1)[0].strip() for name in event_names if ":" in name
    ]
    if event_names and len(prefixes) == len(event_names):
        if len({prefix.casefold() for prefix in prefixes}) == 1:
            return prefixes[0]

    suffix = " Aggregate Contribution Report"
    if title.casefold().endswith(suffix.casefold()):
        series_name = title[: -len(suffix)].strip()
        if series_name:
            return series_name
    return title


def _template_environment(template_dir: Path | None) -> Environment:
    """Create the shared Jinja environment for report templates."""
    if template_dir is None:
        template_dir = _DEFAULT_TEMPLATE_DIR
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_report(
    stats: dict[str, Any],
    config: dict[str, Any],
    activity: dict[str, Any],
    *,
    template_dir: Path | None = None,
) -> str:
    """Render the HTML activity report and return the complete document as a string.

    Parameters
    ----------
    stats:
        Assembled stats dict from ``build_stats`` (``mm.outputs.json_stats``).
    config:
        Loaded and validated event config dict (may include ``_event_dir``).
    activity:
        The specific activity dict from ``config["activities"]`` being rendered.
    template_dir:
        Directory containing ``activity_report.html``.  Defaults to
        ``<repo-root>/templates/``.

    Returns
    -------
    str
        Complete HTML document as a UTF-8 string, ready to write to disk.
    """
    template = _template_environment(template_dir).get_template("activity_report.html")

    # Title / subtitle — prefer event.report overrides, fall back to name/date.
    report_value: object = config.get("report")
    if report_value is None:
        report_cfg: Mapping[object, object] = {}
    elif isinstance(report_value, Mapping):
        report_cfg = cast(Mapping[object, object], report_value)
    else:
        raise TypeError("config.report must be an object")

    report_title = report_cfg.get("title")
    if report_title is not None and not isinstance(report_title, str):
        raise TypeError("config.report.title must be a string")
    event_name_value: object = config.get("name")
    if event_name_value is not None and not isinstance(event_name_value, str):
        raise TypeError("config.name must be a string")
    title = report_title or event_name_value or "Contribution Report"
    date_str: str = config.get("date") or ""
    try:
        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except ValueError:
        # Windows' strftime does not support ``%-d`` on every Python build.
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
            date_display = f"{parsed_date:%B} {parsed_date.day}, {parsed_date:%Y}"
        except ValueError:
            date_display = date_str
    activity_label: str = activity.get("label") or activity.get("id") or ""
    event_id = str(stats.get("event_id") or config.get("id") or "event")
    activity_id = str(stats.get("activity_id") or activity.get("id") or "activity")
    default_subtitle = (
        f"{date_display}\u00a0\u00b7\u00a0{activity_label}"
        if date_display and activity_label
        else (date_display or activity_label)
    )
    report_subtitle = report_cfg.get("subtitle")
    if report_subtitle is not None and not isinstance(report_subtitle, str):
        raise TypeError("config.report.subtitle must be a string")
    subtitle = report_subtitle or default_subtitle

    return template.render(
        page_title=title,
        title=title,
        event_name=event_name_value or title,
        subtitle=subtitle,
        activity_label=activity_label,
        app_version=_APP_VERSION,
        stats=stats,
        export_filename=_export_filename(
            f"{event_id}-{activity_id}",
            suffix="report",
        ),
        # Inline the full stats as safe JSON for JavaScript consumption.
        stats_json=_safe_json(stats),
    )


def render_aggregate_report(
    stats: dict[str, Any],
    *,
    template_dir: Path | None = None,
) -> str:
    """Render the aggregate contribution summary as a complete HTML document."""
    template = _template_environment(template_dir).get_template("aggregate_report.html")
    title = stats.get("title") or "Aggregate Contribution Report"
    aggregate_series_name = _aggregate_series_name(stats, title)
    return template.render(
        page_title=title,
        title=title,
        aggregate_series_name=aggregate_series_name,
        app_version=_APP_VERSION,
        stats=stats,
        export_filename=_export_filename(
            aggregate_series_name,
            suffix="aggregate-report",
        ),
        stats_json=_safe_json(stats),
    )


def write_report(
    html: str,
    output_dir: Path,
    event_id: str,
    activity_id: str,
) -> Path:
    """Write HTML to ``<output_dir>/events/<event_id>/<activity_id>/index.html``.

    Parent directories are created automatically.

    Returns the path to the written file.
    """
    safe_event_id = require_safe_path_component(event_id, "event_id")
    safe_activity_id = require_safe_path_component(activity_id, "activity_id")
    dest = output_dir / "events" / safe_event_id / safe_activity_id / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_text(dest, html)
    return dest
