"""
mm.sources.workspace — TDEI Workspace / POSM source adapter.

Provides four public functions that together implement the workspace
data-fetch pipeline:

    fetch_bbox(env, workspace_id, api_key)
        → BBox (left, bottom, right, top)

    fetch_osm_xml(env, workspace_id, bbox, api_key)
        → bytes  (raw OSM XML)

    parse_osm_xml(xml_bytes)
        → list[Element]  (normalized element dicts)

    filter_by_time(elements, t_start, t_end)
        → list[Element]  (elements whose timestamp ∈ [t_start, t_end))

Authentication uses two headers on every request:
    Authorization: <api_key>
    X-Workspace:   <workspace_id>

``project_group_id`` from the event config is stored as config metadata
and is never used in any HTTP request here.  Access control is managed
by manually adding the Mapping Momentum TDEI account to the relevant
project groups; the API key itself is per-environment, not per-project-group.

Note on XML parsing: ``xml.etree.ElementTree`` does not resolve external
entities by default, making it safe against XXE.  Data is fetched only
from the trusted TDEI Workspace API, so entity-expansion DoS is not a
practical threat; nonetheless the parser is used without any DTD loading.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from mm.common.http import HTTPError, fetch_bytes, fetch_json
from mm.sources.base import Element, Version

# ---------------------------------------------------------------------------
# API base URLs per environment
# ---------------------------------------------------------------------------

# Maps each environment to the authenticated OSM-compatible Workspaces API.
# The newer api.tdei.us v1 routes currently reject valid Workspaces keys.
_BASE_URLS: dict[str, str] = {
    "prod": "https://osm.workspaces.sidewalks.washington.edu",
    "stage": "https://osm.workspaces-stage.sidewalks.washington.edu",
    "dev": "https://osm.workspaces-dev.sidewalks.washington.edu",
}
_MAX_MAP_SPLIT_DEPTH = 12
_MAX_MAP_REQUESTS = 20_000
_MAX_MAP_RESPONSE_BYTES = 100 * 1024 * 1024
_MAX_MAP_PARSE_ATTEMPTS = 2

# ---------------------------------------------------------------------------
# Public type alias
# ---------------------------------------------------------------------------

# Geographic bounding box: (left/minLon, bottom/minLat, right/maxLon, top/maxLat)
# Coordinates are WGS84 decimal degrees.
BBox = tuple[float, float, float, float]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _api_headers(api_key: str, workspace_id: int) -> dict[str, str]:
    """Return the auth headers required by every Workspace API request."""
    return {
        "Authorization": api_key,
        "X-Workspace": str(workspace_id),
    }


def _base_url(env: str) -> str:
    """Return the API base URL for *env*, raising ``ValueError`` if unknown."""
    try:
        return _BASE_URLS[env]
    except KeyError:
        known = ", ".join(sorted(_BASE_URLS))
        raise ValueError(
            f"Unknown workspace environment {env!r}. Expected one of: {known}"
        )


def _parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into a timezone-aware datetime.

    Accepts trailing 'Z' or '+00:00'.  Raises ``ValueError`` if the
    string cannot be parsed or is not UTC.
    """
    normalised = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalised)
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"Timestamp {value!r} is not UTC")
    return dt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_bbox(env: str, workspace_id: int, api_key: str) -> BBox:
    """Fetch the bounding box for *workspace_id* from the Workspace API.

    Parameters
    ----------
    env:
        Target environment (``"prod"``, ``"stage"``, or ``"dev"``).
    workspace_id:
        Numeric workspace identifier.
    api_key:
        TDEI API key for the target environment (prod, stage, or dev).
        One key covers all project groups accessible to the Mapping
        Momentum TDEI account in that environment.

    Returns
    -------
    BBox
        ``(left, bottom, right, top)`` in WGS84 decimal degrees.

    Raises
    ------
    mm.common.http.HTTPError
        On non-2xx response or connection failure.
    ValueError
        If the API response is missing expected bbox fields.
    """
    url = f"{_base_url(env)}/api/0.6/workspaces/{workspace_id}/bbox.json"
    data = fetch_json(url, headers=_api_headers(api_key, workspace_id))
    if not isinstance(data, dict):
        raise ValueError("Workspace bbox response must be a JSON object")
    try:
        bbox = (
            float(data["min_lon"]),
            float(data["min_lat"]),
            float(data["max_lon"]),
            float(data["max_lat"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Workspace bbox response missing expected fields: {exc}"
        ) from exc
    left, bottom, right, top = bbox
    if not all(isfinite(value) for value in bbox):
        raise ValueError(
            "Workspace bbox response contains non-finite coordinates")
    if not (-180 <= left < right <= 180 and -90 <= bottom < top <= 90):
        raise ValueError(f"Workspace bbox coordinates are invalid: {bbox!r}")
    return bbox


def fetch_osm_xml(
    env: str,
    workspace_id: int,
    bbox: BBox,
    api_key: str,
) -> bytes:
    """Fetch the OSM XML map data for *workspace_id* within *bbox*.

    Parameters
    ----------
    env:
        Target environment (``"prod"``, ``"stage"``, or ``"dev"``).
    workspace_id:
        Numeric workspace identifier.
    bbox:
        Bounding box ``(left, bottom, right, top)`` as returned by
        :func:`fetch_bbox`.
    api_key:
        TDEI API key for the target environment (prod, stage, or dev).
        One key covers all project groups accessible to the Mapping
        Momentum TDEI account in that environment.

    Returns
    -------
    bytes
        Raw OSM XML response body.

    Raises
    ------
    mm.common.http.HTTPError
        On non-2xx response or connection failure.
    """
    request_count = [0]
    return _fetch_map_xml(
        env,
        workspace_id,
        bbox,
        api_key,
        depth=0,
        request_count=request_count,
    )


def _fetch_map_xml(
    env: str,
    workspace_id: int,
    bbox: BBox,
    api_key: str,
    *,
    depth: int,
    request_count: list[int],
) -> bytes:
    """Fetch one map tile, recursively splitting truncated responses."""
    left, bottom, right, top = bbox
    bbox_str = f"{left},{bottom},{right},{top}"
    url = f"{_base_url(env)}/api/0.6/map?bbox={bbox_str}"
    headers = _api_headers(api_key, workspace_id)
    headers["Accept"] = "application/xml, text/xml, */*"
    parse_error: ET.ParseError | None = None
    for _attempt in range(_MAX_MAP_PARSE_ATTEMPTS):
        request_count[0] += 1
        if request_count[0] > _MAX_MAP_REQUESTS:
            raise ValueError(
                f"Workspace map request limit ({_MAX_MAP_REQUESTS}) exceeded; "
                "the requested area may be too large or the API response may be "
                "persistently truncated"
            )
        try:
            payload = fetch_bytes(
                url,
                headers=headers,
                max_bytes=_MAX_MAP_RESPONSE_BYTES,
            )
        except HTTPError as exc:
            # The OSM-compatible endpoint uses 404 for an empty tile.
            if str(exc).startswith("HTTP 404"):
                return b'<?xml version="1.0"?><osm version="0.6" />'
            raise

        try:
            ET.fromstring(payload)  # noqa: S314 — trusted API source
            return payload
        except ET.ParseError as exc:
            parse_error = exc

    assert parse_error is not None
    if depth >= _MAX_MAP_SPLIT_DEPTH:
        raise ValueError(
            "Workspace map response remained truncated at the maximum "
            f"tile depth ({_MAX_MAP_SPLIT_DEPTH}) for bbox {bbox!r}"
        ) from parse_error

    try:
        # A malformed response is normally a server-side truncation. Split
        # the bbox and retry each child independently so dense areas do not
        # prevent the rest of the workspace from being downloaded.
        mid_lon = (left + right) / 2
        mid_lat = (bottom + top) / 2
        tiles = (
            (left, bottom, mid_lon, mid_lat),
            (mid_lon, bottom, right, mid_lat),
            (left, mid_lat, mid_lon, top),
            (mid_lon, mid_lat, right, top),
        )
        roots = [
            ET.fromstring(
                _fetch_map_xml(
                    env,
                    workspace_id,
                    tile,
                    api_key,
                    depth=depth + 1,
                    request_count=request_count,
                )
            )
            for tile in tiles
        ]
        combined = roots[0]
        seen: set[tuple[str, str]] = set()
        for child in combined:
            seen.add((child.tag, child.attrib.get("id", "")))
        for tile_root in roots[1:]:
            for child in tile_root:
                key = (child.tag, child.attrib.get("id", ""))
                if key not in seen:
                    combined.append(child)
                    seen.add(key)
        return ET.tostring(combined, encoding="utf-8", xml_declaration=True)
    except ET.ParseError as exc:
        raise ValueError(
            f"Workspace map child response was malformed for bbox {bbox!r}"
        ) from exc


def parse_osm_xml(xml_bytes: bytes) -> list[Element]:
    """Parse raw OSM XML bytes into a list of normalized element dicts.

    Handles ``<node>``, ``<way>``, and ``<relation>`` elements.  All
    attribute values are cast to their natural Python types (``int``,
    ``float``, ``str``).  Elements missing ``timestamp``, ``user``, or
    ``changeset`` attributes are skipped with their absence treated as
    incomplete data from the API.

    Parameters
    ----------
    xml_bytes:
        Raw bytes from the Workspace ``/map`` endpoint (OSM XML format).

    Returns
    -------
    list[Element]
        One dict per OSM element in document order.

    Raises
    ------
    xml.etree.ElementTree.ParseError
        If *xml_bytes* is not well-formed XML.
    """
    root = ET.fromstring(xml_bytes)  # noqa: S314 — trusted TDEI API source
    elements: list[Element] = []

    for elem in root:
        tag = elem.tag
        if tag not in ("node", "way", "relation"):
            continue

        attrib = elem.attrib

        # Skip elements without the metadata required by every metric.
        if not all(
            k in attrib for k in ("id", "timestamp", "user", "uid", "changeset")
        ):
            continue

        entry: Element = {
            "type": tag,
            "id": int(attrib["id"]),
            "timestamp": attrib["timestamp"],
            "user": attrib["user"],
            "uid": int(attrib["uid"]),
            "changeset": int(attrib["changeset"]),
            "tags": {
                child.attrib["k"]: child.attrib["v"]
                for child in elem
                if child.tag == "tag"
            },
        }

        if tag == "node":
            if "lat" in attrib and "lon" in attrib:
                entry["lat"] = float(attrib["lat"])
                entry["lon"] = float(attrib["lon"])

        elif tag == "way":
            entry["nodes"] = [
                int(child.attrib["ref"]) for child in elem if child.tag == "nd"
            ]

        elements.append(entry)

    return elements


def filter_by_time(
    elements: list[Element],
    t_start: datetime,
    t_end: datetime,
) -> list[Element]:
    """Return elements whose ``timestamp`` falls in ``[t_start, t_end)``.

    Comparison is half-open: ``t_start`` is inclusive, ``t_end`` is
    exclusive.  Both *t_start* and *t_end* must be timezone-aware UTC
    ``datetime`` objects.

    Elements with an unparseable ``timestamp`` are silently dropped.

    Parameters
    ----------
    elements:
        Normalized element dicts as produced by :func:`parse_osm_xml`.
    t_start:
        Inclusive start of the filter window (UTC, timezone-aware).
    t_end:
        Exclusive end of the filter window (UTC, timezone-aware).

    Returns
    -------
    list[Element]
        Subset of *elements* within the time window, preserving order.
    """
    result: list[Element] = []
    for elem in elements:
        try:
            ts = _parse_utc(elem["timestamp"])
        except KeyError, ValueError:
            continue
        if t_start <= ts < t_end:
            result.append(elem)
    return result


def filter_actions_by_time(
    actions: list[tuple[str, Element]],
    t_start: datetime,
    t_end: datetime,
) -> list[tuple[str, Element]]:
    """Return changeset actions whose element timestamp is in the event window."""
    filtered: list[tuple[str, Element]] = []
    for action, element in actions:
        timestamp = element.get("timestamp")
        if not timestamp:
            continue
        try:
            parsed = _parse_utc(timestamp)
        except ValueError:
            continue
        if t_start <= parsed < t_end:
            filtered.append((action, element))
    return filtered


# ---------------------------------------------------------------------------
# Convenience: UTC timezone constant
# ---------------------------------------------------------------------------

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Photo tag key (KartaView / picture quests)
# ---------------------------------------------------------------------------

# OSM tag written by the Walkabout app to store a KartaView field-photo URL.
# Confirmed from live data: ext:kartaview_url=https://cdn.kartaview.org/…
PHOTO_TAG_KEY: str = "ext:kartaview_url"

# ---------------------------------------------------------------------------
# Endpoint path templates (assumed — pending confirmation against live API)
# ---------------------------------------------------------------------------
#
# All paths are relative to _base_url(env) and are combined with
# workspace auth headers from _api_headers(api_key, workspace_id).
#
# Expected response shapes (to be confirmed during integration testing):
#
#   _CHANGESETS_PATH  GET  → JSON array of changeset metadata objects:
#       [{"id": 123, "user": "alice", "uid": 10,
#         "created_at": "2026-01-20T19:00:00Z"}, …]
#     Query params: t_start (ISO 8601 UTC), t_end (ISO 8601 UTC)
#
#   _CHANGESET_PATH   GET  → OsmChange XML for a single changeset:
#       <osmChange version="0.6">
#         <create>…</create>
#         <modify>…</modify>
#         <delete>…</delete>
#       </osmChange>
#
#   _NOTES_PATH       GET  → JSON array of note objects:
#       [{"id": 1, "lat": 49.0, "lon": -122.5,
#         "text": "…", "timestamp": "…",
#         "user": "alice", "uid": 10}, …]
#
_CHANGESETS_PATH = "api/0.6/changesets"
_CHANGESET_PATH_TMPL = "api/0.6/changeset/{changeset_id}/download"
_NOTES_PATH = "api/0.6/notes"


# ---------------------------------------------------------------------------
# Internal helpers for quest decoding (used by enrichment functions)
# ---------------------------------------------------------------------------


def _to_utc_str(dt: datetime) -> str:
    """Format a timezone-aware UTC datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_tag_value(quest_def: Any, tag: str, value: str | None) -> str | None:
    """Return the decoded choice label for *(tag, value)*, or *value* itself.

    Returns ``None`` when *value* is ``None``.  Falls back to the raw
    *value* when the tag or choice is not found in *quest_def*.
    """
    if value is None:
        return None
    if quest_def is None:
        return value
    choices = quest_def.tag_value_to_label.get(tag)
    if choices is None:
        return value
    return choices.get(value, value)


def _build_readable_current(tags: dict[str, str], quest_def: Any) -> dict[str, str]:
    """Return decoded current quest tags: ``{tag_key: decoded_label}``.

    Only tags that appear in the quest definition's ``tag_to_title`` are
    included.  Returns an empty dict when *quest_def* is ``None``.
    """
    if quest_def is None:
        return {}
    readable: dict[str, str] = {}
    for tag, value in tags.items():
        if tag not in quest_def.tag_value_to_label:
            continue
        decoded = _decode_tag_value(quest_def, tag, value)
        if decoded is not None:
            readable[tag] = decoded
    return readable


def _build_readable_diff(
    old_tags: dict[str, str],
    new_tags: dict[str, str],
    quest_def: Any,
) -> dict[str, Any]:
    """Return readable diffs between two tag states for quest-tagged keys.

    The result maps each quest tag whose value changed to
    ``{"old": decoded_old | None, "new": decoded_new | None}``.
    Tags that did not change are omitted.  Returns an empty dict when
    *quest_def* is ``None``.
    """
    if quest_def is None:
        return {}
    quest_tags = {
        t
        for t in old_tags.keys() | new_tags.keys()
        if t in quest_def.tag_value_to_label
    }
    result: dict[str, Any] = {}
    for tag in quest_tags:
        old_val = old_tags.get(tag)
        new_val = new_tags.get(tag)
        if old_val != new_val:
            result[tag] = {
                "old": _decode_tag_value(quest_def, tag, old_val),
                "new": _decode_tag_value(quest_def, tag, new_val),
            }
    return result


# ---------------------------------------------------------------------------
# Changeset fetching and parsing
# ---------------------------------------------------------------------------


def fetch_changesets(
    env: str,
    workspace_id: int,
    window_start: datetime,
    window_end: datetime,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch metadata for all changesets active during the event window.

    Parameters
    ----------
    env:
        Target environment (``"prod"``, ``"stage"``, or ``"dev"``).
    workspace_id:
        Numeric workspace identifier.
    window_start:
        Inclusive start of the event time window (UTC, timezone-aware).
    window_end:
        Exclusive end of the event time window (UTC, timezone-aware).
    api_key:
        TDEI API key for the target environment.

    Returns
    -------
    list[dict[str, Any]]
        Changeset metadata objects.  Each dict contains at minimum
        ``"id"`` (int), ``"user"`` (str), ``"uid"`` (int).

    Raises
    ------
    mm.common.http.HTTPError
        On non-2xx response or connection failure.

    Notes
    -----
    The Workspaces OSM-compatible API returns an XML ``<osm>`` document
    containing ``<changeset>`` entries.  The ``time`` query parameter uses
    the inclusive ISO-8601 interval format supported by that API.
    """
    t_start_str = _to_utc_str(window_start)
    t_end_str = _to_utc_str(window_end)
    url = f"{_base_url(env)}/{_CHANGESETS_PATH}?time={t_start_str},{t_end_str}"
    payload = fetch_bytes(url, headers=_api_headers(api_key, workspace_id))
    root = ET.fromstring(payload)  # noqa: S314 — trusted Workspaces API source

    changesets: list[dict[str, Any]] = []
    for changeset in root.findall("changeset"):
        try:
            item: dict[str, Any] = {
                "id": int(changeset.attrib["id"]),
                "uid": int(changeset.attrib["uid"]),
                "user": changeset.attrib["user"],
                "created_at": changeset.attrib["created_at"],
            }
        except KeyError, ValueError:
            continue
        changesets.append(item)
    return changesets


def fetch_changeset_xml(
    env: str,
    workspace_id: int,
    changeset_id: int,
    api_key: str,
) -> bytes:
    """Fetch the OsmChange XML for a single changeset.

    Parameters
    ----------
    env:
        Target environment.
    workspace_id:
        Numeric workspace identifier.
    changeset_id:
        The numeric changeset ID to download.
    api_key:
        TDEI API key for the target environment.

    Returns
    -------
    bytes
        Raw OsmChange XML response body.

    Raises
    ------
    mm.common.http.HTTPError
        On non-2xx response or connection failure.

    Notes
    -----
    The download route is the standard OSM-compatible Workspaces route.
    """
    path = _CHANGESET_PATH_TMPL.format(changeset_id=changeset_id)
    url = f"{_base_url(env)}/{path}"
    return fetch_bytes(url, headers=_api_headers(api_key, workspace_id))


def parse_osmchange(xml_bytes: bytes) -> list[tuple[str, Element]]:
    """Parse an OsmChange XML document into (action, element) pairs.

    Handles ``<create>``, ``<modify>``, and ``<delete>`` sections.
    Within each section, ``<node>``, ``<way>``, and ``<relation>``
    elements are extracted using the same attribute-extraction logic as
    :func:`parse_osm_xml`.  Elements missing required metadata are
    silently skipped.

    Parameters
    ----------
    xml_bytes:
        Raw OsmChange XML bytes (e.g. from :func:`fetch_changeset_xml`).

    Returns
    -------
    list[tuple[str, Element]]
        Each tuple is ``(action, element)`` where *action* is one of
        ``"create"``, ``"modify"``, or ``"delete"``.

    Raises
    ------
    xml.etree.ElementTree.ParseError
        If *xml_bytes* is not well-formed XML.
    """
    root = ET.fromstring(xml_bytes)  # noqa: S314 — trusted TDEI API source
    results: list[tuple[str, Element]] = []

    for section in root:
        action = section.tag  # "create" | "modify" | "delete"
        if action not in ("create", "modify", "delete"):
            continue

        for elem in section:
            tag = elem.tag
            if tag not in ("node", "way", "relation"):
                continue

            attrib = elem.attrib
            if not all(
                k in attrib for k in ("id", "timestamp", "user", "uid", "changeset")
            ):
                continue

            entry: Element = {
                "type": tag,
                "id": int(attrib["id"]),
                "timestamp": attrib["timestamp"],
                "user": attrib["user"],
                "uid": int(attrib["uid"]),
                "changeset": int(attrib["changeset"]),
                "tags": {
                    child.attrib["k"]: child.attrib["v"]
                    for child in elem
                    if child.tag == "tag"
                },
            }

            if tag == "node":
                if "lat" in attrib and "lon" in attrib:
                    entry["lat"] = float(attrib["lat"])
                    entry["lon"] = float(attrib["lon"])
            elif tag == "way":
                entry["nodes"] = [
                    int(child.attrib["ref"]) for child in elem if child.tag == "nd"
                ]

            results.append((action, entry))

    return results


def build_version_histories(
    actions: list[tuple[str, Element]],
    quest_def: Any = None,
) -> dict[tuple[str, int], list[Version]]:
    """Assemble per-element version histories from OsmChange action pairs.

    Groups ``(action, element)`` pairs by ``(type, id)``, sorts each group
    by ``timestamp`` ascending, and constructs :class:`~mm.sources.base.Version`
    dicts with readable quest diffs between consecutive versions.

    Parameters
    ----------
    actions:
        List of ``(action, element)`` tuples as returned by
        :func:`parse_osmchange`.  Multiple changeset files should be
        concatenated before calling this function.
    quest_def:
        Optional :class:`~mm.quests.loader.QuestDefinition` for decoding
        tag values into human-readable labels and computing diffs.
        When ``None``, all ``readable`` fields are empty dicts.

    Returns
    -------
    dict[tuple[str, int], list[Version]]
        Maps ``(element_type, element_id)`` to its ordered version list
        (oldest-first).
    """
    # Collect raw action groups keyed by (type, id)
    groups: dict[tuple[str, int], list[tuple[str, Element]]] = {}
    for action, elem in actions:
        key = (elem["type"], elem["id"])
        groups.setdefault(key, []).append((action, elem))

    histories: dict[tuple[str, int], list[Version]] = {}
    for key in sorted(groups):
        group = groups[key]
        # Sort by timestamp ascending; fall back to stable order on ties
        group.sort(key=lambda t: (t[1].get("timestamp", ""), t[0]))

        versions: list[Version] = []
        prev_tags: dict[str, str] = {}
        for action, elem in group:
            current_tags = elem.get("tags", {})
            readable_diff = _build_readable_diff(
                prev_tags, current_tags, quest_def)
            photos = extract_photos(current_tags)
            versions.append(
                Version(
                    action=action,
                    user=elem.get("user", ""),
                    timestamp=elem.get("timestamp", ""),
                    changeset=elem.get("changeset", 0),
                    tags=current_tags,
                    readable=readable_diff,
                    photos=photos,
                )
            )
            prev_tags = current_tags

        histories[key] = versions

    return histories


def enrich_elements(
    map_elements: list[Element],
    histories: dict[tuple[str, int], list[Version]],
    quest_def: Any = None,
) -> list[Element]:
    """Merge map-snapshot elements with changeset version histories.

    For each element that has a version history, attaches the history,
    derives ``kind``, ``category``, ``readable`` (current decoded tags),
    and ``photos``.  The ``geom`` field is set to ``None``; callers should
    run :func:`resolve_way_geometry` afterwards.

    Elements present in *histories* but absent from *map_elements*
    (i.e. deleted during the event) are reconstructed from their last
    known version and included in the output.

    Parameters
    ----------
    map_elements:
        Normalized elements from the ``/map`` snapshot, already filtered
        to the event time window by :func:`filter_by_time`.
    histories:
        Version histories per ``(element_type, element_id)`` as returned
        by :func:`build_version_histories`.
    quest_def:
        Optional :class:`~mm.quests.loader.QuestDefinition` for
        category and readable-label derivation.

    Returns
    -------
    list[Element]
        Enriched element dicts ready for metric consumption and rendering.
    """
    # Index map elements by (type, id) for O(1) lookup
    map_index: dict[tuple[str, int], Element] = {
        (e["type"], e["id"]): e for e in map_elements
    }

    enriched: list[Element] = []
    seen: set[tuple[str, int]] = set()

    def _enrich(elem: Element, versions: list[Version]) -> Element:
        """Return a copy of *elem* augmented with enriched fields."""
        result = dict(elem)
        result["versions"] = versions

        # kind — "create" if the element's first version is a create action
        first_action = versions[0]["action"] if versions else "modify"
        result["kind"] = "create" if first_action == "create" else "quest"

        # category — derived from quest definition
        tags: dict[str, str] = result.get("tags", {})
        if quest_def is not None:
            category = ""
            for tag_key in tags:
                if tag_key in quest_def.tag_to_category:
                    category = quest_def.tag_to_category[tag_key]
                    break
            result["category"] = category
        else:
            result["category"] = ""

        # readable — decoded current-state tags
        result["readable"] = _build_readable_current(tags, quest_def)

        # photos — from PHOTO_TAG_KEY in current tags
        result["photos"] = extract_photos(tags)

        # geom — placeholder; caller runs resolve_way_geometry
        result.setdefault("geom", None)

        return result

    # Process elements that have version histories
    for key, versions in histories.items():
        seen.add(key)
        if key in map_index:
            enriched.append(_enrich(map_index[key], versions))
        else:
            # Element was deleted — reconstruct from last version
            last = versions[-1]
            reconstructed: Element = {
                "type": key[0],
                "id": key[1],
                "timestamp": last["timestamp"],
                "user": last["user"],
                "uid": 0,
                "changeset": last["changeset"],
                "tags": last["tags"],
            }
            enriched.append(_enrich(reconstructed, versions))

    # Map elements with no version history (mapped outside the event)
    # are skipped — they do not represent event activity.

    return enriched


# ---------------------------------------------------------------------------
# Notes fetching and parsing
# ---------------------------------------------------------------------------


def fetch_notes(
    env: str,
    workspace_id: int,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch all notes for the workspace.

    Parameters
    ----------
    env:
        Target environment.
    workspace_id:
        Numeric workspace identifier.
    api_key:
        TDEI API key for the target environment.

    Returns
    -------
    list[dict[str, Any]]
        Raw note objects.  Each dict contains at minimum ``"id"``,
        ``"lat"``, ``"lon"``, ``"text"``, ``"timestamp"``, ``"user"``,
        and ``"uid"``.

    Raises
    ------
    mm.common.http.HTTPError
        On non-2xx response or connection failure.

    Notes
    -----
    The endpoint returns the OSM-compatible XML notes document.  The current
    response does not include author fields, so note parsing uses an empty
    author and UID zero when those fields are unavailable.
    """
    bbox = fetch_bbox(env, workspace_id, api_key)
    left, bottom, right, top = bbox
    url = f"{_base_url(env)}/{_NOTES_PATH}?bbox={left},{bottom},{right},{top}"
    payload = fetch_bytes(url, headers=_api_headers(api_key, workspace_id))
    root = ET.fromstring(payload)  # noqa: S314 — trusted Workspaces API source

    notes: list[dict[str, Any]] = []
    for note in root.findall("note"):
        try:
            comment = note.find("./comments/comment")
            date_created = note.findtext("date_created", "")
            user = ""
            uid = 0
            if comment is not None:
                user = comment.attrib.get("user", "")
                uid = int(comment.attrib.get("uid", "0"))
            notes.append(
                {
                    "id": int(note.findtext("id", "0")),
                    "lat": float(note.attrib["lat"]),
                    "lon": float(note.attrib["lon"]),
                    "text": note.findtext("./comments/comment/text", ""),
                    "timestamp": _normalise_note_timestamp(date_created),
                    "user": user,
                    "uid": uid,
                }
            )
        except KeyError, TypeError, ValueError:
            continue
    return notes


def _normalise_note_timestamp(value: str) -> str:
    """Convert a Workspaces note timestamp to an ISO-8601 UTC string."""
    if not value:
        return ""
    return value.replace(" UTC", "Z").replace(" ", "T")


def parse_changesets(
    changeset_payloads: Iterable[bytes | list[tuple[str, Element]]],
    quest_def: Any = None,
) -> dict[tuple[str, int], list[Version]]:
    """Parse and combine several changeset documents into version histories.

    ``changeset_payloads`` accepts either raw OsmChange XML bytes or already
    parsed action pairs.  Supporting both forms keeps the aggregation logic
    useful for the live pipeline and for offline golden fixtures.  Histories
    are sorted by element type/id and timestamp, so response ordering cannot
    change report output.
    """
    actions: list[tuple[str, Element]] = []
    for payload in changeset_payloads:
        if isinstance(payload, bytes):
            actions.extend(parse_osmchange(payload))
        else:
            actions.extend(payload)
    return build_version_histories(actions, quest_def=quest_def)


def parse_notes(
    raw_notes: list[dict[str, Any]],
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> list[Element]:
    """Convert raw note objects into note-kind :data:`~mm.sources.base.Element` dicts.

    Each note becomes an element with ``kind="note"``, ``type="note"``,
    ``text``, ``lat``, ``lon``, and the standard metadata fields.  Notes
    missing ``lat``, ``lon``, ``text``, ``user``, or ``uid`` are silently
    skipped.

    Parameters
    ----------
    raw_notes:
        Raw note dicts as returned by :func:`fetch_notes`.
    window_start:
        When provided, notes before this timestamp are excluded
        (inclusive lower bound, UTC).
    window_end:
        When provided, notes at or after this timestamp are excluded
        (exclusive upper bound, UTC).

    Returns
    -------
    list[Element]
        Note elements with ``kind="note"``, ``category=""``,
        ``versions=[]``, ``photos=[]``, ``readable={}``,
        ``geom=None``.
    """
    elements: list[Element] = []
    for note in raw_notes:
        # Skip notes with missing required fields
        if not all(k in note for k in ("lat", "lon", "text", "user", "uid")):
            continue

        timestamp = note.get("timestamp", "")
        if window_start is not None or window_end is not None:
            if not timestamp:
                continue
            try:
                ts = _parse_utc(timestamp)
            except ValueError:
                continue
            if window_start is not None and ts < window_start:
                continue
            if window_end is not None and ts >= window_end:
                continue

        elements.append(
            {
                "type": "note",
                "id": note.get("id", 0),
                "timestamp": timestamp,
                "user": note["user"],
                "uid": note["uid"],
                "changeset": 0,
                "tags": {},
                "lat": float(note["lat"]),
                "lon": float(note["lon"]),
                "text": note["text"],
                "kind": "note",
                "category": "",
                "versions": [],
                "photos": [],
                "readable": {},
                "geom": None,
            }
        )
    return elements


# ---------------------------------------------------------------------------
# Geometry resolution
# ---------------------------------------------------------------------------


def resolve_way_geometry(
    elements: list[Element],
    coordinate_source: Iterable[Element] | None = None,
) -> None:
    """Add ``geom`` to way elements by resolving member-node coordinates.

    Builds a coordinate lookup from all node elements in *coordinate_source*
    when supplied, otherwise from *elements*,
    then for each way element constructs ``geom`` as a list of
    ``[lat, lon]`` pairs corresponding to the way's ``nodes`` ref list.
    Node refs without a matching coordinate are omitted from the polyline.

    Nodes without ``lat``/``lon`` (e.g. nodes outside the bbox) are
    silently skipped in the coordinate lookup.

    This function modifies *elements* in place.

    Parameters
    ----------
    elements:
        Mixed list of nodes, ways, and other elements from the pipeline.
        Both enriched and un-enriched elements are supported.
    coordinate_source:
        Optional complete map snapshot used to resolve nodes that are not
        themselves event-edited elements.  This is important for ways whose
        member nodes were created before the event window.
    """
    source = coordinate_source if coordinate_source is not None else elements
    node_coords: dict[int, tuple[float, float]] = {
        e["id"]: (e["lat"], e["lon"])
        for e in source
        if e.get("type") == "node" and "lat" in e and "lon" in e
    }

    for elem in elements:
        if elem.get("type") == "way" and "nodes" in elem:
            coords = [
                [node_coords[nid][0], node_coords[nid][1]]
                for nid in elem["nodes"]
                if nid in node_coords
            ]
            elem["geom"] = coords if coords else None


# ---------------------------------------------------------------------------
# KartaView photo extraction
# ---------------------------------------------------------------------------


def extract_photos(
    tags: dict[str, str],
    photo_tag_key: str = PHOTO_TAG_KEY,
) -> list[str]:
    """Extract KartaView field-photo URLs from element tags.

    Looks up *photo_tag_key* in *tags* and returns a single-item list
    containing the URL if present, or an empty list.

    Parameters
    ----------
    tags:
        OSM tag dict from an element or a version snapshot.
    photo_tag_key:
        The tag key used by the Walkabout app to store photo URLs.
        Defaults to :data:`PHOTO_TAG_KEY`.  Override to test with
        alternative keys.

    Returns
    -------
    list[str]
        Zero or one photo URL.

    Notes
    -----
    The exact tag key is assumed pending confirmation from the TDEI API.
    """
    url = tags.get(photo_tag_key)
    return [url] if url else []
