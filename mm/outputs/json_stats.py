"""
mm.outputs.json_stats — assemble and write stats.json for one event activity.

stats.json is the authoritative data payload consumed by both the HTML report
renderer and downstream tooling.  It is deterministic: re-running the pipeline
against the same source data and committed quest definition always produces an
identical file.

Schema (v1)
-----------
All scalar metric keys from the registered compute functions, plus::

    {
      "activity_id":  str,
      "source_type":  str,
      "window_start": str,            # ISO 8601 UTC
      "window_end":   str,
      "markers": [                    # one per mappable element
        {
          "id":       int,
          "type":     str,            # "node" | "way" | "relation" | "note"
          "kind":     str,            # "quest" | "create" | "note"
          "category": str,
          "lat":      float,
          "lon":      float,
          "geom":     [[lat, lon], …] | null,
          "tags":     {str: str},
          "readable": {str: str},
          "photos":   [str],
          "versions": [{…}],
          "text":     str             # note body; "" for map elements
        },
        …
      ],
      "showcase_photos": [{"src": str, "caption": str}, …]
    }
"""

from __future__ import annotations

import base64
import importlib
import inspect
from pathlib import Path
from typing import Any

from mm.common.io import require_safe_path_component, write_json
from mm.metrics.base import get_metrics_for_source
from mm.sources.base import Element, SourceResult

# Import all metric modules so they self-register.
for _metric_module in (
    "mm.metrics.changeset_count",
    "mm.metrics.contributor_count",
    "mm.metrics.contributors_breakdown",
    "mm.metrics.elements_edited",
    "mm.metrics.features_created",
    "mm.metrics.node_count",
    "mm.metrics.notes",
    "mm.metrics.quest_types",
    "mm.metrics.questions_answered",
    "mm.metrics.relation_count",
    "mm.metrics.way_count",
):
    importlib.import_module(_metric_module)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _marker_latlon(elem: Element) -> tuple[float, float] | None:
    """Return (lat, lon) for an element, or ``None`` if not mappable.

    Nodes and notes carry explicit ``lat``/``lon``.  Ways derive a
    representative point from the centroid of their ``geom`` polyline.
    """
    lat = elem.get("lat")
    lon = elem.get("lon")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    geom = elem.get("geom")
    if geom:
        lats = [p[0] for p in geom]
        lons = [p[1] for p in geom]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    return None


def _build_marker(elem: Element) -> dict[str, Any] | None:
    """Build a map marker payload dict from an enriched element.

    Returns ``None`` for elements that cannot be placed on the map (no
    position information available).
    """
    pos = _marker_latlon(elem)
    if pos is None:
        return None
    lat, lon = pos
    return {
        "id": elem.get("id"),
        "type": elem.get("type"),
        "kind": elem.get("kind", "quest"),
        "category": elem.get("category", ""),
        "lat": lat,
        "lon": lon,
        "geom": elem.get("geom"),
        "tags": elem.get("tags", {}),
        "readable": elem.get("readable", {}),
        "photos": elem.get("photos", []),
        # Top-level user/timestamp: the authoritative fallback for elements
        # with no version history (notes are never changeset-versioned; see
        # mm.sources.workspace.parse_notes).  The popup renderer uses these
        # whenever ``versions`` is empty so note authorship/timestamp/text
        # are never silently dropped.
        "user": elem.get("user", ""),
        "timestamp": elem.get("timestamp", ""),
        "versions": [
            {
                "action": v["action"],
                "user": v["user"],
                "timestamp": v["timestamp"],
                "changeset": v["changeset"],
                "tags": v["tags"],
                "readable": v["readable"],
                "photos": v["photos"],
            }
            for v in elem.get("versions", [])
        ],
        "text": elem.get("text", ""),
    }


# Explicit extension -> MIME type map. Deliberately not using the stdlib
# ``mimetypes`` module: its guesses are sourced from the OS registry/config
# and vary across platforms (e.g. Windows maps ".jpg" to "application/jpg"),
# which would make embedded data URIs non-deterministic across environments.
_IMAGE_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _guess_image_mime(path: Path) -> str:
    """Return the MIME type for *path* based on its suffix, defaulting to
    ``image/jpeg`` for unrecognised extensions."""
    return _IMAGE_MIME_TYPES.get(path.suffix.lower(), "image/jpeg")


def _resolve_showcase_photos(
    photos: list[dict],
    event_dir: Path | None,
) -> list[dict]:
    """Resolve showcase photo ``src`` values for inline HTML embedding.

    URL sources are passed through unchanged.  Local paths (relative to
    *event_dir*) are read from disk and embedded as ``data:`` URIs so the
    resulting stats.json / HTML report is fully self-contained.
    """
    result: list[dict] = []
    for photo in photos:
        src: str = photo.get("src", "")
        caption: str = photo.get("caption", "")
        if not src:
            continue
        if src.startswith(("http://", "https://", "data:")):
            result.append({"src": src, "caption": caption})
        elif event_dir is not None:
            photo_path = event_dir / src
            if photo_path.exists():
                mime = _guess_image_mime(photo_path)
                encoded = base64.b64encode(photo_path.read_bytes()).decode()
                result.append(
                    {"src": f"data:{mime};base64,{encoded}", "caption": caption}
                )
        else:
            # No event_dir provided — keep original src
            result.append({"src": src, "caption": caption})
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_stats(
    result: SourceResult,
    *,
    quest_def: Any = None,
    showcase_photos: list[dict] | None = None,
    event_dir: Path | None = None,
) -> dict[str, Any]:
    """Assemble the full stats dict for one activity.

    Runs all metric modules registered for ``result.source_type``, builds
    the ``markers`` and ``showcase_photos`` payloads, and combines
    everything into a single serialisable dict.

    Parameters
    ----------
    result:
        Enriched ``SourceResult`` from the workspace pipeline.
    quest_def:
        Optional ``QuestDefinition`` forwarded to metrics that accept it
        (currently ``questions_answered``).
    showcase_photos:
        List of ``{"src": str, "caption": str}`` dicts from the event
        config.  Local paths are embedded as data URIs when *event_dir*
        is provided.
    event_dir:
        Path to the event directory.  Used to resolve relative showcase
        photo paths.

    Returns
    -------
    dict[str, Any]
        Complete stats payload ready to serialise as ``stats.json``.
    """
    elements = result.elements

    stats: dict[str, Any] = {
        "activity_id": result.activity_id,
        "source_type": result.source_type,
        "window_start": result.window_start.isoformat(),
        "window_end": result.window_end.isoformat(),
    }

    # Run every registered metric, forwarding quest_def when the function
    # accepts it.
    for compute_fn in get_metrics_for_source(result.source_type):
        sig = inspect.signature(compute_fn)
        if "quest_def" in sig.parameters:
            stats.update(compute_fn(elements, quest_def=quest_def))
        else:
            stats.update(compute_fn(elements))

    # Map markers — one per element that has a position.
    stats["markers"] = [
        m for elem in elements if (m := _build_marker(elem)) is not None
    ]

    # Showcase photos with local paths converted to data URIs.
    stats["showcase_photos"] = _resolve_showcase_photos(
        showcase_photos or [], event_dir
    )

    return stats


def write_stats(
    stats: dict[str, Any],
    output_dir: Path,
    event_id: str,
    activity_id: str,
) -> Path:
    """Write *stats* to ``<output_dir>/events/<event_id>/<activity_id>/stats.json``.

    Parent directories are created automatically.

    Returns the path to the written file.
    """
    safe_event_id = require_safe_path_component(event_id, "event_id")
    safe_activity_id = require_safe_path_component(activity_id, "activity_id")
    dest = output_dir / "events" / safe_event_id / safe_activity_id / "stats.json"
    write_json(dest, stats)
    return dest
