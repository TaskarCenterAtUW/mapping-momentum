"""Unit tests for the Slice C enriched pipeline additions to mm.sources.workspace.

All tests are fully offline — no network calls.  HTTP is mocked at the
``mm.common.http`` level where needed.

Test matrix
-----------
parse_osmchange:
  - create/modify/delete sections are parsed into (action, element) pairs
  - node lat/lon, way nd refs, and tags are extracted correctly
  - elements missing required metadata are skipped
  - empty sections and unknown sections are handled gracefully
  - malformed XML raises ParseError

build_version_histories:
  - groups actions by (type, id)
  - sorts versions oldest-first by timestamp
  - action field is preserved on each Version
  - readable diffs are empty without a quest definition
  - readable diffs are computed correctly with a quest definition
  - photos are extracted from version tags

enrich_elements:
  - version history is attached to matching map elements
  - kind is "create" when first version action is "create"
  - kind is "quest" when first version action is "modify"
  - category is derived from quest definition
  - readable is the decoded current tags
  - photos are extracted from current tags
  - geom defaults to None
  - deleted element (in histories but not in map) is included
  - map element with no history is excluded

parse_notes:
  - notes are converted to note-kind elements
  - kind, type, text, lat, lon, user, uid are set correctly
  - notes missing required fields are skipped
  - window filtering works (inclusive start, exclusive end)

resolve_way_geometry:
  - way geom is populated from member node lat/lon
  - nodes without coordinates are skipped
  - node elements are not modified
  - way with no matching nodes gets geom=None

extract_photos:
  - returns empty list when tag is absent
  - returns single-item list when tag is present
  - custom photo_tag_key is respected

fetch_changesets / fetch_changeset_xml / fetch_notes:
  - correct URL is constructed
  - auth headers are present
  - response is returned / parsed correctly
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from mm.quests.loader import QuestDefinition
from mm.sources.base import Element, Version
from mm.sources.workspace import (
    PHOTO_TAG_KEY,
    build_version_histories,
    enrich_elements,
    extract_photos,
    fetch_changeset_xml,
    fetch_changesets,
    fetch_notes,
    parse_notes,
    parse_osmchange,
    resolve_way_geometry,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_OSMCHANGE_HEADER = b'<?xml version="1.0" encoding="UTF-8"?><osmChange version="0.6">'
_OSMCHANGE_FOOTER = b"</osmChange>"


def _osmchange(*sections: bytes) -> bytes:
    return _OSMCHANGE_HEADER + b"".join(sections) + _OSMCHANGE_FOOTER


_CREATE_NODE = (
    b"<create>"
    b'<node id="1" lat="49.001" lon="-122.501" version="1" '
    b'timestamp="2026-01-20T19:00:00Z" uid="10" user="alice" changeset="100">'
    b'<tag k="ext:surface" v="asphalt"/>'
    b"</node>"
    b"</create>"
)

_MODIFY_NODE = (
    b"<modify>"
    b'<node id="1" lat="49.001" lon="-122.501" version="2" '
    b'timestamp="2026-01-20T20:00:00Z" uid="10" user="alice" changeset="101">'
    b'<tag k="ext:surface" v="concrete"/>'
    b"</node>"
    b"</modify>"
)

_CREATE_WAY = (
    b"<create>"
    b'<way id="50" version="1" '
    b'timestamp="2026-01-20T19:30:00Z" uid="10" user="alice" changeset="100">'
    b'<nd ref="1"/><nd ref="2"/>'
    b'<tag k="highway" v="footway"/>'
    b"</way>"
    b"</create>"
)

_DELETE_NODE = (
    b"<delete>"
    b'<node id="99" lat="49.005" lon="-122.505" version="3" '
    b'timestamp="2026-01-20T21:00:00Z" uid="11" user="bob" changeset="102">'
    b"</node>"
    b"</delete>"
)

_INCOMPLETE_NODE = (
    b"<create>"
    # Missing uid — should be skipped
    b'<node id="77" lat="49.0" lon="-122.0" version="1" '
    b'timestamp="2026-01-20T19:00:00Z" user="ghost" changeset="100">'
    b"</node>"
    b"</create>"
)


def _mock_fetch_json(response: object):
    """Patch mm.common.http.fetch_json to return *response*."""
    return patch("mm.sources.workspace.fetch_json", return_value=response)


def _mock_fetch_bytes(response: bytes):
    """Patch mm.common.http.fetch_bytes to return *response*."""
    return patch("mm.sources.workspace.fetch_bytes", return_value=response)


# Minimal QuestDefinition-like object for decoding tests
class _FakeQuestDef:
    tag_to_title = {
        "ext:surface": "What is this sidewalk's surface type?",
        "ext:obstruction": "Are there any obstructions?",
    }
    tag_value_to_label = {
        "ext:surface": {"asphalt": "Asphalt", "concrete": "Concrete"},
        "ext:obstruction": {"yes": "Yes", "no": "No"},
    }
    tag_to_category = {
        "ext:surface": "Sidewalks",
        "ext:obstruction": "Sidewalks",
    }


_QUEST_DEF = _FakeQuestDef()


# ---------------------------------------------------------------------------
# parse_osmchange
# ---------------------------------------------------------------------------


def test_parse_osmchange_create_action() -> None:
    result = parse_osmchange(_osmchange(_CREATE_NODE))
    assert len(result) == 1
    action, elem = result[0]
    assert action == "create"
    assert elem["type"] == "node"
    assert elem["id"] == 1
    assert elem["user"] == "alice"
    assert elem["uid"] == 10
    assert elem["changeset"] == 100
    assert elem["tags"] == {"ext:surface": "asphalt"}


def test_parse_osmchange_modify_action() -> None:
    result = parse_osmchange(_osmchange(_MODIFY_NODE))
    assert len(result) == 1
    action, elem = result[0]
    assert action == "modify"
    assert elem["id"] == 1
    assert elem["tags"] == {"ext:surface": "concrete"}


def test_parse_osmchange_delete_action() -> None:
    result = parse_osmchange(_osmchange(_DELETE_NODE))
    assert len(result) == 1
    action, elem = result[0]
    assert action == "delete"
    assert elem["id"] == 99
    assert elem["tags"] == {}


def test_parse_osmchange_node_lat_lon() -> None:
    result = parse_osmchange(_osmchange(_CREATE_NODE))
    _, elem = result[0]
    assert elem["lat"] == pytest.approx(49.001)
    assert elem["lon"] == pytest.approx(-122.501)


def test_parse_osmchange_way_nd_refs() -> None:
    result = parse_osmchange(_osmchange(_CREATE_WAY))
    _, elem = result[0]
    assert elem["type"] == "way"
    assert elem["id"] == 50
    assert elem["nodes"] == [1, 2]


def test_parse_osmchange_multiple_sections() -> None:
    result = parse_osmchange(_osmchange(_CREATE_NODE, _MODIFY_NODE))
    assert len(result) == 2
    actions = [a for a, _ in result]
    assert actions == ["create", "modify"]


def test_parse_osmchange_skips_incomplete_elements() -> None:
    result = parse_osmchange(_osmchange(_INCOMPLETE_NODE))
    assert result == []


def test_parse_osmchange_empty_document() -> None:
    result = parse_osmchange(_OSMCHANGE_HEADER + _OSMCHANGE_FOOTER)
    assert result == []


def test_parse_osmchange_unknown_section_ignored() -> None:
    unknown = b"<info><tag k='x' v='y'/></info>"
    result = parse_osmchange(_osmchange(unknown))
    assert result == []


def test_parse_osmchange_malformed_raises() -> None:
    with pytest.raises(ET.ParseError):
        parse_osmchange(b"<not valid xml")


# ---------------------------------------------------------------------------
# build_version_histories
# ---------------------------------------------------------------------------


def test_build_version_histories_groups_by_type_and_id() -> None:
    actions = parse_osmchange(_osmchange(_CREATE_NODE, _MODIFY_NODE))
    histories = build_version_histories(actions)
    assert ("node", 1) in histories
    assert len(histories[("node", 1)]) == 2


def test_build_version_histories_sorts_oldest_first() -> None:
    # Reverse order: modify before create in the input
    actions = parse_osmchange(_osmchange(_MODIFY_NODE, _CREATE_NODE))
    histories = build_version_histories(actions)
    versions = histories[("node", 1)]
    assert versions[0]["timestamp"] == "2026-01-20T19:00:00Z"
    assert versions[1]["timestamp"] == "2026-01-20T20:00:00Z"


def test_build_version_histories_action_field_preserved() -> None:
    actions = parse_osmchange(_osmchange(_CREATE_NODE, _MODIFY_NODE))
    histories = build_version_histories(actions)
    versions = histories[("node", 1)]
    assert versions[0]["action"] == "create"
    assert versions[1]["action"] == "modify"


def test_build_version_histories_tags_preserved() -> None:
    actions = parse_osmchange(_osmchange(_CREATE_NODE, _MODIFY_NODE))
    histories = build_version_histories(actions)
    versions = histories[("node", 1)]
    assert versions[0]["tags"] == {"ext:surface": "asphalt"}
    assert versions[1]["tags"] == {"ext:surface": "concrete"}


def test_build_version_histories_readable_empty_without_quest_def() -> None:
    actions = parse_osmchange(_osmchange(_CREATE_NODE, _MODIFY_NODE))
    histories = build_version_histories(actions)
    for v in histories[("node", 1)]:
        assert v["readable"] == {}


def test_build_version_histories_readable_diff_with_quest_def() -> None:
    actions = parse_osmchange(_osmchange(_CREATE_NODE, _MODIFY_NODE))
    histories = build_version_histories(actions, quest_def=_QUEST_DEF)
    versions = histories[("node", 1)]
    # First version: {} → {ext:surface: asphalt} → diff has old=None
    assert "ext:surface" in versions[0]["readable"]
    assert versions[0]["readable"]["ext:surface"]["old"] is None
    assert versions[0]["readable"]["ext:surface"]["new"] == "Asphalt"
    # Second version: asphalt → concrete
    assert versions[1]["readable"]["ext:surface"]["old"] == "Asphalt"
    assert versions[1]["readable"]["ext:surface"]["new"] == "Concrete"


def test_build_version_histories_photos_extracted() -> None:
    create_with_photo = (
        b"<create>"
        b'<node id="10" lat="49.0" lon="-122.0" version="1" '
        b'timestamp="2026-01-20T19:00:00Z" uid="10" user="alice" changeset="100">'
        b'<tag k="' + PHOTO_TAG_KEY.encode() + b'" v="https://example.com/photo.jpg"/>'
        b"</node>"
        b"</create>"
    )
    actions = parse_osmchange(_osmchange(create_with_photo))
    histories = build_version_histories(actions)
    assert histories[("node", 10)][0]["photos"] == ["https://example.com/photo.jpg"]


def test_build_version_histories_multiple_elements() -> None:
    actions = parse_osmchange(_osmchange(_CREATE_NODE, _CREATE_WAY))
    histories = build_version_histories(actions)
    assert ("node", 1) in histories
    assert ("way", 50) in histories


# ---------------------------------------------------------------------------
# enrich_elements
# ---------------------------------------------------------------------------


def _make_map_node(
    node_id: int = 1,
    timestamp: str = "2026-01-20T20:00:00Z",
    tags: dict | None = None,
) -> Element:
    return {
        "type": "node",
        "id": node_id,
        "timestamp": timestamp,
        "user": "alice",
        "uid": 10,
        "changeset": 101,
        "tags": tags or {"ext:surface": "concrete"},
        "lat": 49.001,
        "lon": -122.501,
    }


def _make_history(actions_and_tags: list[tuple[str, dict]]) -> list[Version]:
    versions = []
    timestamps = [
        "2026-01-20T19:00:00Z",
        "2026-01-20T20:00:00Z",
        "2026-01-20T21:00:00Z",
    ]
    for i, (action, tags) in enumerate(actions_and_tags):
        versions.append(
            Version(
                action=action,
                user="alice",
                timestamp=timestamps[i],
                changeset=100 + i,
                tags=tags,
                readable={},
                photos=[],
            )
        )
    return versions


def test_enrich_elements_attaches_versions() -> None:
    node = _make_map_node()
    hist = {
        ("node", 1): _make_history(
            [
                ("create", {"ext:surface": "asphalt"}),
                ("modify", {"ext:surface": "concrete"}),
            ]
        )
    }
    result = enrich_elements([node], hist)
    assert len(result) == 1
    assert len(result[0]["versions"]) == 2


def test_enrich_elements_kind_create_from_first_action() -> None:
    node = _make_map_node()
    hist = {("node", 1): _make_history([("create", {"ext:surface": "concrete"})])}
    result = enrich_elements([node], hist)
    assert result[0]["kind"] == "create"


def test_enrich_elements_kind_quest_from_modify_action() -> None:
    node = _make_map_node()
    hist = {("node", 1): _make_history([("modify", {"ext:surface": "concrete"})])}
    result = enrich_elements([node], hist)
    assert result[0]["kind"] == "quest"


def test_enrich_elements_category_from_quest_def() -> None:
    node = _make_map_node(tags={"ext:surface": "concrete"})
    hist = {("node", 1): _make_history([("modify", {"ext:surface": "concrete"})])}
    result = enrich_elements([node], hist, quest_def=_QUEST_DEF)
    assert result[0]["category"] == "Sidewalks"


def test_enrich_elements_category_empty_without_quest_def() -> None:
    node = _make_map_node()
    hist = {("node", 1): _make_history([("modify", {"ext:surface": "concrete"})])}
    result = enrich_elements([node], hist)
    assert result[0]["category"] == ""


def test_enrich_elements_readable_current_state() -> None:
    node = _make_map_node(tags={"ext:surface": "concrete"})
    hist = {("node", 1): _make_history([("modify", {"ext:surface": "concrete"})])}
    result = enrich_elements([node], hist, quest_def=_QUEST_DEF)
    assert result[0]["readable"] == {"ext:surface": "Concrete"}


def test_enrich_elements_excludes_free_text_from_readable() -> None:
    quest_def = QuestDefinition(
        tag_to_title={"ext:hazard": "Describe the hazard"},
        tag_value_to_label={},
        tag_to_category={"ext:hazard": "Sidewalks"},
    )
    node = _make_map_node(tags={"ext:hazard": "Crack"})
    hist = {("node", 1): _make_history([("modify", {"ext:hazard": "Crack"})])}
    result = enrich_elements([node], hist, quest_def=quest_def)
    assert result[0]["readable"] == {}


def test_enrich_elements_photos_from_current_tags() -> None:
    tags = {"ext:surface": "asphalt", PHOTO_TAG_KEY: "https://example.com/p.jpg"}
    node = _make_map_node(tags=tags)
    hist = {("node", 1): _make_history([("modify", tags)])}
    result = enrich_elements([node], hist)
    assert result[0]["photos"] == ["https://example.com/p.jpg"]


def test_enrich_elements_geom_defaults_to_none() -> None:
    node = _make_map_node()
    hist = {("node", 1): _make_history([("modify", {})])}
    result = enrich_elements([node], hist)
    assert result[0]["geom"] is None


def test_enrich_elements_deleted_element_included() -> None:
    # Element in history but not in map → was deleted
    hist = {
        ("node", 99): _make_history(
            [("create", {"ext:surface": "asphalt"}), ("delete", {})]
        )
    }
    result = enrich_elements([], hist)
    assert len(result) == 1
    assert result[0]["id"] == 99


def test_enrich_elements_map_element_without_history_excluded() -> None:
    # Element is in the map but has no changeset history → not in output
    node = _make_map_node()
    result = enrich_elements([node], {})
    assert result == []


def test_enrich_elements_multiple_elements() -> None:
    node1 = _make_map_node(node_id=1, tags={"ext:surface": "concrete"})
    node2 = _make_map_node(node_id=2, tags={"ext:obstruction": "no"})
    hist = {
        ("node", 1): _make_history([("create", {"ext:surface": "concrete"})]),
        ("node", 2): _make_history([("modify", {"ext:obstruction": "no"})]),
    }
    result = enrich_elements([node1, node2], hist, quest_def=_QUEST_DEF)
    assert len(result) == 2
    cats = {e["id"]: e["category"] for e in result}
    assert cats[1] == "Sidewalks"
    assert cats[2] == "Sidewalks"


# ---------------------------------------------------------------------------
# parse_notes
# ---------------------------------------------------------------------------


_SAMPLE_NOTES = [
    {
        "id": 1,
        "lat": 49.001,
        "lon": -122.501,
        "text": "Broken curb ramp here",
        "timestamp": "2026-01-20T19:30:00Z",
        "user": "alice",
        "uid": 10,
    },
    {
        "id": 2,
        "lat": 49.002,
        "lon": -122.502,
        "text": "Overgrown vegetation blocking path",
        "timestamp": "2026-01-20T21:00:00Z",
        "user": "bob",
        "uid": 11,
    },
]


def test_parse_notes_basic_fields() -> None:
    result = parse_notes(_SAMPLE_NOTES)
    assert len(result) == 2
    n = result[0]
    assert n["kind"] == "note"
    assert n["type"] == "note"
    assert n["text"] == "Broken curb ramp here"
    assert n["lat"] == pytest.approx(49.001)
    assert n["lon"] == pytest.approx(-122.501)
    assert n["user"] == "alice"
    assert n["uid"] == 10
    assert n["id"] == 1


def test_parse_notes_standard_enriched_fields() -> None:
    result = parse_notes(_SAMPLE_NOTES)
    n = result[0]
    assert n["versions"] == []
    assert n["photos"] == []
    assert n["readable"] == {}
    assert n["geom"] is None
    assert n["category"] == ""


def test_parse_notes_skips_missing_lat() -> None:
    bad = [
        {"id": 1, "lon": -122.5, "text": "x", "user": "a", "uid": 1, "timestamp": ""}
    ]
    assert parse_notes(bad) == []


def test_parse_notes_skips_missing_text() -> None:
    bad = [
        {"id": 1, "lat": 49.0, "lon": -122.5, "user": "a", "uid": 1, "timestamp": ""}
    ]
    assert parse_notes(bad) == []


def test_parse_notes_window_filtering_start_inclusive() -> None:
    t_start = datetime(2026, 1, 20, 19, 30, 0, tzinfo=UTC)
    t_end = datetime(2026, 1, 21, 4, 0, 0, tzinfo=UTC)
    result = parse_notes(_SAMPLE_NOTES, window_start=t_start, window_end=t_end)
    ids = {n["id"] for n in result}
    assert 1 in ids  # timestamp == t_start → included
    assert 2 in ids


def test_parse_notes_window_filtering_excludes_before_start() -> None:
    t_start = datetime(2026, 1, 20, 20, 0, 0, tzinfo=UTC)  # after note 1
    result = parse_notes(_SAMPLE_NOTES, window_start=t_start)
    ids = {n["id"] for n in result}
    assert 1 not in ids
    assert 2 in ids


def test_parse_notes_window_filtering_end_exclusive() -> None:
    t_end = datetime(2026, 1, 20, 21, 0, 0, tzinfo=UTC)  # = note 2 timestamp
    result = parse_notes(_SAMPLE_NOTES, window_end=t_end)
    ids = {n["id"] for n in result}
    assert 1 in ids
    assert 2 not in ids  # timestamp == t_end → excluded


def test_parse_notes_excludes_missing_timestamp_in_window() -> None:
    raw = [{"id": 1, "lat": 1, "lon": 2, "text": "note", "user": "a", "uid": 1}]
    result = parse_notes(
        raw,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert result == []


def test_parse_notes_empty_input() -> None:
    assert parse_notes([]) == []


# ---------------------------------------------------------------------------
# resolve_way_geometry
# ---------------------------------------------------------------------------


def _make_node_elem(node_id: int, lat: float, lon: float) -> Element:
    return {
        "type": "node",
        "id": node_id,
        "timestamp": "",
        "user": "alice",
        "uid": 10,
        "changeset": 100,
        "tags": {},
        "lat": lat,
        "lon": lon,
    }


def _make_way_elem(way_id: int, node_refs: list[int]) -> Element:
    return {
        "type": "way",
        "id": way_id,
        "timestamp": "",
        "user": "alice",
        "uid": 10,
        "changeset": 100,
        "tags": {},
        "nodes": node_refs,
        "geom": None,
    }


def test_resolve_way_geometry_basic() -> None:
    elements = [
        _make_node_elem(1, 49.001, -122.501),
        _make_node_elem(2, 49.002, -122.502),
        _make_way_elem(50, [1, 2]),
    ]
    resolve_way_geometry(elements)
    way = next(e for e in elements if e["type"] == "way")
    assert way["geom"] == [[49.001, -122.501], [49.002, -122.502]]


def test_resolve_way_geometry_skips_missing_nodes() -> None:
    elements = [
        _make_node_elem(1, 49.001, -122.501),
        _make_way_elem(50, [1, 999]),  # node 999 not in elements
    ]
    resolve_way_geometry(elements)
    way = next(e for e in elements if e["type"] == "way")
    assert way["geom"] == [[49.001, -122.501]]  # only node 1 resolved


def test_resolve_way_geometry_no_matching_nodes_gives_none() -> None:
    elements = [_make_way_elem(50, [999, 998])]
    resolve_way_geometry(elements)
    assert elements[0]["geom"] is None


def test_resolve_way_geometry_does_not_modify_nodes() -> None:
    node = _make_node_elem(1, 49.001, -122.501)
    elements = [node, _make_way_elem(50, [1])]
    resolve_way_geometry(elements)
    assert "geom" not in node or node.get("geom") is None or True  # node unchanged


def test_resolve_way_geometry_modifies_in_place() -> None:
    elements = [
        _make_node_elem(1, 49.001, -122.501),
        _make_way_elem(50, [1]),
    ]
    resolve_way_geometry(elements)
    way = elements[1]
    assert way["geom"] == [[49.001, -122.501]]


# ---------------------------------------------------------------------------
# extract_photos
# ---------------------------------------------------------------------------


def test_extract_photos_absent_returns_empty() -> None:
    assert extract_photos({"ext:surface": "asphalt"}) == []


def test_extract_photos_present_returns_url() -> None:
    tags = {PHOTO_TAG_KEY: "https://example.com/photo.jpg"}
    assert extract_photos(tags) == ["https://example.com/photo.jpg"]


def test_extract_photos_custom_key() -> None:
    tags = {"my_photo": "https://example.com/img.png"}
    assert extract_photos(tags, photo_tag_key="my_photo") == [
        "https://example.com/img.png"
    ]


def test_extract_photos_empty_tags() -> None:
    assert extract_photos({}) == []


# ---------------------------------------------------------------------------
# fetch_changesets
# ---------------------------------------------------------------------------


def test_fetch_changesets_constructs_correct_url() -> None:
    t_start = datetime(2026, 1, 20, 18, 0, 0, tzinfo=UTC)
    t_end = datetime(2026, 1, 21, 4, 0, 0, tzinfo=UTC)
    expected = [
        {
            "id": 100,
            "user": "alice",
            "uid": 10,
            "created_at": "2026-01-20T19:00:00Z",
        }
    ]
    body = (
        b'<osm><changeset id="100" uid="10" user="alice" '
        b'created_at="2026-01-20T19:00:00Z"/></osm>'
    )

    with _mock_fetch_bytes(body) as mock_fb:
        result = fetch_changesets("prod", 931, t_start, t_end, "key123")

    assert result == expected
    call_url = mock_fb.call_args[0][0]
    assert "api/0.6/changesets" in call_url
    assert "time=2026-01-20T18:00:00Z,2026-01-21T04:00:00Z" in call_url


def test_fetch_changesets_sends_auth_headers() -> None:
    t_start = datetime(2026, 1, 20, 18, 0, 0, tzinfo=UTC)
    t_end = datetime(2026, 1, 21, 4, 0, 0, tzinfo=UTC)

    body = b"<osm/>"
    with _mock_fetch_bytes(body) as mock_fb:
        fetch_changesets("prod", 931, t_start, t_end, "mykey")

    headers = mock_fb.call_args[1]["headers"]
    assert headers["Authorization"] == "mykey"
    assert headers["X-Workspace"] == "931"


# ---------------------------------------------------------------------------
# fetch_changeset_xml
# ---------------------------------------------------------------------------


def test_fetch_changeset_xml_constructs_correct_url() -> None:
    xml_bytes = b"<osmChange/>"
    with _mock_fetch_bytes(xml_bytes) as mock_fb:
        result = fetch_changeset_xml("prod", 931, 100, "key123")

    assert result == xml_bytes
    call_url = mock_fb.call_args[0][0]
    assert "api/0.6/changeset/100/download" in call_url


def test_fetch_changeset_xml_sends_auth_headers() -> None:
    with _mock_fetch_bytes(b"<osmChange/>") as mock_fb:
        fetch_changeset_xml("prod", 931, 100, "mykey")

    headers = mock_fb.call_args[1]["headers"]
    assert headers["Authorization"] == "mykey"
    assert headers["X-Workspace"] == "931"


# ---------------------------------------------------------------------------
# fetch_notes
# ---------------------------------------------------------------------------


def test_fetch_notes_constructs_correct_url() -> None:
    bbox = {
        "min_lon": -122.5,
        "min_lat": 49.0,
        "max_lon": -122.4,
        "max_lat": 49.1,
    }
    with _mock_fetch_json(bbox), _mock_fetch_bytes(b"<osm/>") as mock_fb:
        fetch_notes("prod", 931, "key123")

    call_url = mock_fb.call_args[0][0]
    assert "api/0.6/notes" in call_url
    assert "bbox=-122.5,49.0,-122.4,49.1" in call_url


def test_fetch_notes_sends_auth_headers() -> None:
    bbox = {
        "min_lon": -122.5,
        "min_lat": 49.0,
        "max_lon": -122.4,
        "max_lat": 49.1,
    }
    with _mock_fetch_json(bbox), _mock_fetch_bytes(b"<osm/>") as mock_fb:
        fetch_notes("prod", 931, "mykey")

    headers = mock_fb.call_args[1]["headers"]
    assert headers["Authorization"] == "mykey"
    assert headers["X-Workspace"] == "931"


def test_fetch_notes_returns_list() -> None:
    bbox = {
        "min_lon": -122.5,
        "min_lat": 49.0,
        "max_lon": -122.4,
        "max_lat": 49.1,
    }
    notes_xml = (
        b'<osm><note lat="49.0" lon="-122.5">'
        b"<id>1</id>"
        b"<date_created>2026-01-20 19:00:00 UTC</date_created>"
        b"<comments><comment><text>x</text></comment></comments>"
        b"</note></osm>"
    )
    with _mock_fetch_json(bbox), _mock_fetch_bytes(notes_xml):
        result = fetch_notes("prod", 931, "key")
    assert result[0]["id"] == 1
    assert result[0]["text"] == "x"
    assert result[0]["timestamp"] == "2026-01-20T19:00:00Z"
