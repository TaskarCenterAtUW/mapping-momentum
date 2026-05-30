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
from mm.sources.base import Element

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
