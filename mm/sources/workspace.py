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
from datetime import datetime, timedelta, timezone
from typing import Any

from mm.common.http import fetch_bytes, fetch_json
from mm.sources.base import Element, Version

# ---------------------------------------------------------------------------
# API base URLs per environment
# ---------------------------------------------------------------------------

# Maps the ``environment`` field from the activity config to the TDEI API
# base URL.  Endpoints are appended as path segments below.
_BASE_URLS: dict[str, str] = {
    "prod": "https://api.tdei.us",
    "stage": "https://api-stage.tdei.us",
    "dev": "https://api-dev.tdei.us",
}

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
            f"Unknown workspace environment {env!r}. "
            f"Expected one of: {known}"
        )


def _parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into a timezone-aware datetime.

    Accepts trailing 'Z' or '+00:00'.  Raises ``ValueError`` if the
    string cannot be parsed or is not UTC.
    """
    normalised = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalised)
    if dt.utcoffset() != timedelta(0):
        raise ValueError(
            f"Timestamp {value!r} is not UTC"
        )
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
    url = f"{_base_url(env)}/api/v1/workspace/bbox"
    data: dict[str, Any] = fetch_json(
        url, headers=_api_headers(api_key, workspace_id)
    )
    try:
        return (
            float(data["minLon"]),
            float(data["minLat"]),
            float(data["maxLon"]),
            float(data["maxLat"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"Workspace bbox response missing expected fields: {exc}"
        ) from exc


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
    left, bottom, right, top = bbox
    bbox_str = f"{left},{bottom},{right},{top}"
    url = f"{_base_url(env)}/api/v1/workspace/map?bbox={bbox_str}"
    return fetch_bytes(url, headers=_api_headers(api_key, workspace_id))


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
                int(child.attrib["ref"])
                for child in elem
                if child.tag == "nd"
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
        except (KeyError, ValueError):
            continue
        if t_start <= ts < t_end:
            result.append(elem)
    return result


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
_CHANGESETS_PATH = "api/v1/workspace/changesets"
_CHANGESET_PATH_TMPL = "api/v1/workspace/changeset/{changeset_id}"
_NOTES_PATH = "api/v1/workspace/notes"


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


def _build_readable_current(
    tags: dict[str, str], quest_def: Any
) -> dict[str, str]:
    """Return decoded current quest tags: ``{tag_key: decoded_label}``.

    Only tags that appear in the quest definition's ``tag_to_title`` are
    included.  Returns an empty dict when *quest_def* is ``None``.
    """
    if quest_def is None:
        return {}
    return {
        tag: _decode_tag_value(quest_def, tag, value)  # type: ignore[misc]
        for tag, value in tags.items()
        if tag in quest_def.tag_to_title
    }


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
        if t in quest_def.tag_to_title
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
    Endpoint and query-parameter names are assumed pending confirmation
    against the live TDEI Workspace API.
    """
    t_start_str = _to_utc_str(window_start)
    t_end_str = _to_utc_str(window_end)
    url = (
        f"{_base_url(env)}/{_CHANGESETS_PATH}"
        f"?t_start={t_start_str}&t_end={t_end_str}"
    )
    return fetch_json(url, headers=_api_headers(api_key, workspace_id))


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
    Endpoint path is assumed pending confirmation against the live API.
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
                    int(child.attrib["ref"])
                    for child in elem
                    if child.tag == "nd"
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
    for key, group in groups.items():
        # Sort by timestamp ascending; fall back to stable order on ties
        try:
            group.sort(key=lambda t: _parse_utc(t[1]["timestamp"]))
        except (KeyError, ValueError):
            pass  # preserve insertion order if timestamps are unparseable

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
    Endpoint path and response shape are assumed pending confirmation
    against the live TDEI Workspace API.
    """
    url = f"{_base_url(env)}/{_NOTES_PATH}"
    return fetch_json(url, headers=_api_headers(api_key, workspace_id))


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
        if timestamp and (window_start is not None or window_end is not None):
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


def resolve_way_geometry(elements: list[Element]) -> None:
    """Add ``geom`` to way elements by resolving member-node coordinates.

    Builds a coordinate lookup from all node elements in *elements*,
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
    """
    node_coords: dict[int, tuple[float, float]] = {
        e["id"]: (e["lat"], e["lon"])
        for e in elements
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
