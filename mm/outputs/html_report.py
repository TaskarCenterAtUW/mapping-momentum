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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from mm.common.io import require_safe_path_component, write_text

# Hatch installs shared data under the interpreter prefix. The repository
# fallback keeps source-checkout execution convenient.
_INSTALLED_TEMPLATE_DIR = Path(sys.prefix) / "templates"
_SOURCE_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"
_DEFAULT_TEMPLATE_DIR = (
    _INSTALLED_TEMPLATE_DIR
    if (_INSTALLED_TEMPLATE_DIR / "activity_report.html").is_file()
    else _SOURCE_TEMPLATE_DIR
)


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
    if template_dir is None:
        template_dir = _DEFAULT_TEMPLATE_DIR

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("activity_report.html")

    # Title / subtitle — prefer event.report overrides, fall back to name/date.
    report_cfg: dict = config.get("report") or {}
    title: str = report_cfg.get("title") or config.get("name") or "Contribution Report"
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
    default_subtitle = (
        f"{date_display}\u00a0\u00b7\u00a0{activity_label}"
        if date_display and activity_label
        else (date_display or activity_label)
    )
    subtitle: str = report_cfg.get("subtitle") or default_subtitle

    return template.render(
        page_title=title,
        title=title,
        subtitle=subtitle,
        activity_label=activity_label,
        stats=stats,
        # Inline the full stats as safe JSON for JavaScript consumption.
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
