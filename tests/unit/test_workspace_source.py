"""Unit tests for mm.sources.workspace.

All tests are fully offline — no network calls are made.  HTTP is mocked
at the ``urllib.request.urlopen`` level.

Test matrix:
  parse_osm_xml:
    - nodes, ways, and relations are parsed correctly
    - node lat/lon are extracted; way node-refs are extracted
    - tags are parsed into a dict
    - elements missing required metadata attributes are skipped
    - empty <osm> document returns an empty list
    - malformed XML raises ParseError

  filter_by_time:
    - element at exactly t_start is included (inclusive lower bound)
    - element at exactly t_end is excluded (exclusive upper bound)
    - element strictly inside the window is included
    - element before t_start is excluded
    - element after t_end is excluded
    - element with unparseable timestamp is silently skipped
    - empty input returns empty list

  fetch_bbox:
    - successful response is parsed into a (left, bottom, right, top) tuple
    - response missing a required key raises ValueError
    - HTTP error propagates as HTTPError

  fetch_osm_xml:
    - successful response bytes are returned unchanged
    - auth headers are present in the request
    - HTTP error propagates as HTTPError
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from mm.sources.workspace import (
    BBox,
    fetch_bbox,
    fetch_osm_xml,
    filter_by_time,
    parse_osm_xml,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc

# Minimal valid OSM XML fixture used across multiple tests.
_OSM_HEADER = b'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6">'
_OSM_FOOTER = b"</osm>"

_NODE_ALICE = (
    b'<node id="1" lat="49.001" lon="-122.501" version="1" '
    b'timestamp="2026-01-20T20:00:00Z" uid="10" user="alice" changeset="100">'
    b'<tag k="sidewalk" v="yes"/></node>'
)
_NODE_BOB = (
    b'<node id="2" lat="49.002" lon="-122.502" version="1" '
    b'timestamp="2026-01-20T22:00:00Z" uid="11" user="bob" changeset="101">'
    b"</node>"
)
_WAY_ALICE = (
    b'<way id="50" version="1" '
    b'timestamp="2026-01-20T21:00:00Z" uid="10" user="alice" changeset="100">'
    b'<nd ref="1"/><nd ref="2"/>'
    b'<tag k="highway" v="footway"/></way>'
)
# Node missing uid (should be skipped).
_NODE_INCOMPLETE = (
    b'<node id="99" lat="49.0" lon="-122.0" version="1" '
    b'timestamp="2026-01-20T20:30:00Z" user="ghost" changeset="200">'
    b"</node>"
)

_FULL_OSM = _OSM_HEADER + _NODE_ALICE + _NODE_BOB + _WAY_ALICE + _OSM_FOOTER
_INCOMPLETE_OSM = _OSM_HEADER + _NODE_INCOMPLETE + _NODE_ALICE + _OSM_FOOTER


def _osm(*body_parts: bytes) -> bytes:
    """Wrap *body_parts* in <osm> tags."""
    return _OSM_HEADER + b"".join(body_parts) + _OSM_FOOTER


def _mock_urlopen(body: bytes, status: int = 200):
    """Return a context-manager mock for ``urllib.request.urlopen``."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# parse_osm_xml — happy path
# ---------------------------------------------------------------------------


def test_parse_osm_xml_node() -> None:
    elements = parse_osm_xml(_osm(_NODE_ALICE))
    assert len(elements) == 1
    node = elements[0]
    assert node["type"] == "node"
    assert node["id"] == 1
    assert node["user"] == "alice"
    assert node["uid"] == 10
    assert node["changeset"] == 100
    assert node["timestamp"] == "2026-01-20T20:00:00Z"
    assert node["lat"] == pytest.approx(49.001)
    assert node["lon"] == pytest.approx(-122.501)
    assert node["tags"] == {"sidewalk": "yes"}


def test_parse_osm_xml_node_no_tags() -> None:
    elements = parse_osm_xml(_osm(_NODE_BOB))
    assert elements[0]["tags"] == {}


def test_parse_osm_xml_way() -> None:
    elements = parse_osm_xml(_osm(_WAY_ALICE))
    assert len(elements) == 1
    way = elements[0]
    assert way["type"] == "way"
    assert way["id"] == 50
    assert way["nodes"] == [1, 2]
    assert way["tags"] == {"highway": "footway"}


def test_parse_osm_xml_multiple_elements() -> None:
    elements = parse_osm_xml(_FULL_OSM)
    assert len(elements) == 3
    types = [e["type"] for e in elements]
    assert types == ["node", "node", "way"]


def test_parse_osm_xml_skips_incomplete_elements() -> None:
    # _NODE_INCOMPLETE is missing 'uid'; it should be skipped.
    elements = parse_osm_xml(_INCOMPLETE_OSM)
    assert len(elements) == 1
    assert elements[0]["id"] == 1  # only _NODE_ALICE survives


def test_parse_osm_xml_empty_document() -> None:
    elements = parse_osm_xml(_OSM_HEADER + _OSM_FOOTER)
    assert elements == []


def test_parse_osm_xml_malformed_raises() -> None:
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        parse_osm_xml(b"<not valid xml")


def test_parse_osm_xml_ignores_non_element_tags() -> None:
    bounds = b'<bounds minlat="49.0" minlon="-122.6" maxlat="49.1" maxlon="-122.4"/>'
    elements = parse_osm_xml(_osm(bounds, _NODE_ALICE))
    assert len(elements) == 1  # bounds tag ignored; only the node returned


# ---------------------------------------------------------------------------
# filter_by_time
# ---------------------------------------------------------------------------

_ELEMENTS = [
    {
        "type": "node",
        "id": 1,
        "timestamp": "2026-01-20T18:00:00Z",  # = t_start (inclusive)
        "user": "alice",
        "uid": 10,
        "changeset": 100,
        "tags": {},
    },
    {
        "type": "node",
        "id": 2,
        "timestamp": "2026-01-20T20:00:00Z",  # strictly inside
        "user": "bob",
        "uid": 11,
        "changeset": 101,
        "tags": {},
    },
    {
        "type": "way",
        "id": 50,
        "timestamp": "2026-01-21T04:00:00Z",  # = t_end (exclusive)
        "user": "alice",
        "uid": 10,
        "changeset": 100,
        "tags": {},
        "nodes": [],
    },
    {
        "type": "node",
        "id": 3,
        "timestamp": "2026-01-20T17:59:59Z",  # before t_start
        "user": "carol",
        "uid": 12,
        "changeset": 102,
        "tags": {},
    },
    {
        "type": "node",
        "id": 4,
        "timestamp": "2026-01-21T04:00:01Z",  # after t_end
        "user": "dave",
        "uid": 13,
        "changeset": 103,
        "tags": {},
    },
]

_T_START = datetime(2026, 1, 20, 18, 0, 0, tzinfo=UTC)
_T_END = datetime(2026, 1, 21, 4, 0, 0, tzinfo=UTC)


def test_filter_includes_t_start() -> None:
    result = filter_by_time(_ELEMENTS, _T_START, _T_END)
    ids = {e["id"] for e in result}
    assert 1 in ids  # timestamp == t_start → included


def test_filter_excludes_t_end() -> None:
    result = filter_by_time(_ELEMENTS, _T_START, _T_END)
    ids = {e["id"] for e in result}
    assert 50 not in ids  # timestamp == t_end → excluded


def test_filter_includes_interior_element() -> None:
    result = filter_by_time(_ELEMENTS, _T_START, _T_END)
    ids = {e["id"] for e in result}
    assert 2 in ids


def test_filter_excludes_before_start() -> None:
    result = filter_by_time(_ELEMENTS, _T_START, _T_END)
    ids = {e["id"] for e in result}
    assert 3 not in ids


def test_filter_excludes_after_end() -> None:
    result = filter_by_time(_ELEMENTS, _T_START, _T_END)
    ids = {e["id"] for e in result}
    assert 4 not in ids


def test_filter_result_count() -> None:
    result = filter_by_time(_ELEMENTS, _T_START, _T_END)
    # Elements 1 (t_start inclusive) and 2 (inside) should pass.
    assert len(result) == 2


def test_filter_empty_input() -> None:
    result = filter_by_time([], _T_START, _T_END)
    assert result == []


def test_filter_skips_bad_timestamp() -> None:
    bad = [
        {
            "type": "node",
            "id": 99,
            "timestamp": "not-a-timestamp",
            "user": "x",
            "uid": 0,
            "changeset": 0,
            "tags": {},
        }
    ]
    result = filter_by_time(bad, _T_START, _T_END)
    assert result == []


# ---------------------------------------------------------------------------
# fetch_bbox
# ---------------------------------------------------------------------------


def test_fetch_bbox_returns_tuple() -> None:
    body = json.dumps(
        {"minLon": -122.5, "minLat": 49.0, "maxLon": -122.4, "maxLat": 49.1}
    ).encode()
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
        bbox = fetch_bbox("prod", 931, "test-key")
    assert bbox == (-122.5, 49.0, -122.4, 49.1)


def test_fetch_bbox_missing_field_raises() -> None:
    # Response is missing maxLat.
    body = json.dumps({"minLon": -122.5, "minLat": 49.0, "maxLon": -122.4}).encode()
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
        with pytest.raises(ValueError, match="missing expected fields"):
            fetch_bbox("prod", 931, "test-key")


def test_fetch_bbox_http_error_propagates() -> None:
    from mm.common.http import HTTPError

    http_exc = urllib.error.HTTPError(
        url="http://x",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    with patch("urllib.request.urlopen", side_effect=http_exc):
        with pytest.raises(HTTPError, match="401"):
            fetch_bbox("prod", 931, "bad-key")


def test_fetch_bbox_unknown_env_raises() -> None:
    with pytest.raises(ValueError, match="Unknown workspace environment"):
        fetch_bbox("staging", 931, "test-key")


# ---------------------------------------------------------------------------
# fetch_osm_xml
# ---------------------------------------------------------------------------


def test_fetch_osm_xml_returns_bytes() -> None:
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_FULL_OSM)):
        result = fetch_osm_xml("prod", 931, (-122.5, 49.0, -122.4, 49.1), "key")
    assert result == _FULL_OSM


def test_fetch_osm_xml_includes_auth_headers() -> None:
    captured_req: list = []

    def fake_urlopen(req, timeout=30):
        captured_req.append(req)
        return _mock_urlopen(b"<osm/>")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        fetch_osm_xml("prod", 931, (-122.5, 49.0, -122.4, 49.1), "my-api-key")

    req = captured_req[0]
    assert req.get_header("Authorization") == "my-api-key"
    assert req.get_header("X-workspace") == "931"


def test_fetch_osm_xml_http_error_propagates() -> None:
    from mm.common.http import HTTPError

    http_exc = urllib.error.HTTPError(
        url="http://x",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=None,  # type: ignore[arg-type]
    )
    with patch("urllib.request.urlopen", side_effect=http_exc):
        with pytest.raises(HTTPError, match="403"):
            fetch_osm_xml("prod", 931, (-122.5, 49.0, -122.4, 49.1), "key")


def test_fetch_osm_xml_bbox_in_url() -> None:
    captured_req: list = []

    def fake_urlopen(req, timeout=30):
        captured_req.append(req)
        return _mock_urlopen(b"<osm/>")

    bbox: BBox = (-122.5, 49.0, -122.4, 49.1)
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        fetch_osm_xml("prod", 931, bbox, "key")

    url = captured_req[0].full_url
    assert "bbox=-122.5,49.0,-122.4,49.1" in url
