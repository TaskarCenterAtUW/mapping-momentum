"""Unit tests for mm.outputs.json_stats and mm.outputs.html_report.

All tests are fully offline — no network calls, no CDN loading.

Test matrix
-----------
build_stats:
  - returns required top-level keys
  - runs all registered metrics on elements
  - markers built for nodes with lat/lon
  - markers built for ways using geom centroid
  - elements without position are excluded from markers
  - note markers get kind="note" and grey representation
  - showcase_photos passed through (URL sources unchanged)
  - local showcase paths embedded as data URIs when event_dir provided
  - quest_def forwarded to questions_answered metric

write_stats:
  - writes stats.json to correct path
  - written JSON is parseable and matches input

_safe_json:
  - escapes < > & to Unicode sequences
  - output is valid JSON

render_report:
  - returns non-empty HTML string
  - <html lang="en"> is present (S1 — WCAG 3.1.1)
  - exactly one <h1> element (S2)
  - page_title appears in <title> and <h1>
  - subtitle appears in output
  - activity_label appears in h2
  - changeset_count and note_count badges present
  - stats_json inlined without raw < or > characters
  - Quest Types card present when data available
  - Features Created card present
  - Contributors card present
  - Questions Answered section present when data available
  - showcase section present only when showcase_photos non-empty
  - photo modal dialog present
  - map container present
  - skip link present (K4)
  - graceful render with empty stats

write_report:
  - writes index.html to correct path
  - file contains the rendered HTML
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from mm.outputs.anonymize import anonymize_stats
from mm.outputs.html_report import render_report, write_report
from mm.outputs.json_stats import build_stats, write_stats
from mm.sources.base import Element, SourceResult

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_source_result(elements: list[Element] | None = None) -> SourceResult:
    return SourceResult(
        source_type="workspace",
        activity_id="walkabout",
        window_start=datetime(2026, 1, 20, 18, 0, 0, tzinfo=UTC),
        window_end=datetime(2026, 1, 21, 4, 0, 0, tzinfo=UTC),
        elements=elements or [],
    )


def _enriched_node(
    id_: int = 1,
    user: str = "alice",
    kind: str = "quest",
    category: str = "Sidewalks",
    lat: float = 49.001,
    lon: float = -122.501,
    tags: dict[str, str] | None = None,
    readable: dict[str, Any] | None = None,
    photos: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "node",
        "id": id_,
        "timestamp": "2026-01-20T20:00:00Z",
        "user": user,
        "uid": 10,
        "changeset": 100,
        "tags": tags or {"ext:surface": "asphalt"},
        "lat": lat,
        "lon": lon,
        "kind": kind,
        "category": category,
        "versions": [
            {
                "action": "create" if kind == "create" else "modify",
                "user": user,
                "timestamp": "2026-01-20T20:00:00Z",
                "changeset": 100,
                "tags": tags or {"ext:surface": "asphalt"},
                "readable": readable or {"ext:surface": "Asphalt"},
                "photos": photos or [],
            }
        ],
        "photos": photos or [],
        "readable": readable or {"ext:surface": "Asphalt"},
        "geom": None,
    }


def _enriched_way(id_: int = 50, user: str = "bob") -> dict[str, Any]:
    return {
        "type": "way",
        "id": id_,
        "timestamp": "2026-01-20T20:00:00Z",
        "user": user,
        "uid": 11,
        "changeset": 101,
        "tags": {"highway": "footway"},
        "nodes": [1, 2],
        "kind": "create",
        "category": "Sidewalks",
        "versions": [],
        "photos": [],
        "readable": {},
        "geom": [[49.001, -122.501], [49.002, -122.502]],
    }


def _note_element(id_: int = 99, user: str = "carol") -> dict[str, Any]:
    return {
        "type": "note",
        "id": id_,
        "timestamp": "2026-01-20T20:30:00Z",
        "user": user,
        "uid": 12,
        "changeset": 0,
        "tags": {},
        "lat": 49.003,
        "lon": -122.503,
        "kind": "note",
        "category": "",
        "versions": [],
        "photos": [],
        "readable": {},
        "geom": None,
        "text": "A field note",
    }


def _minimal_config(*, showcase: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "type": "event",
        "id": "test-event",
        "name": "Test Event",
        "date": "2026-01-20",
        "activities": [
            {
                "id": "walkabout",
                "type": "workspace",
                "label": "Test Walk/Roll",
                "project_group_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "workspace_id": 1,
                "environment": "prod",
                "quest_definition_url": "https://example.com/quest.json",
                "time_window": {
                    "start": "2026-01-20T18:00:00Z",
                    "end": "2026-01-21T04:00:00Z",
                },
            }
        ],
        **({"showcase_photos": showcase} if showcase is not None else {}),
    }


# ---------------------------------------------------------------------------
# build_stats
# ---------------------------------------------------------------------------


def test_build_stats_required_keys() -> None:
    result = build_stats(_make_source_result())
    for key in (
        "activity_id",
        "source_type",
        "window_start",
        "window_end",
        "markers",
        "showcase_photos",
    ):
        assert key in result, f"missing key: {key}"


def test_build_stats_activity_metadata() -> None:
    sr = _make_source_result()
    stats = build_stats(sr)
    assert stats["activity_id"] == "walkabout"
    assert stats["source_type"] == "workspace"
    assert "2026" in stats["window_start"]


def test_build_stats_runs_metrics() -> None:
    elements = [_enriched_node(id_=1, user="alice"), _enriched_node(id_=2, user="bob")]
    stats = build_stats(_make_source_result(elements))
    assert "changeset_count" in stats
    assert "contributor_count" in stats
    assert "quest_type_breakdown" in stats


def test_build_stats_marker_from_node() -> None:
    node = _enriched_node(id_=1, lat=49.001, lon=-122.501)
    stats = build_stats(_make_source_result([node]))
    markers = stats["markers"]
    assert len(markers) == 1
    assert math.isclose(markers[0]["lat"], 49.001, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(markers[0]["lon"], -122.501, rel_tol=0.0, abs_tol=1e-9)
    assert markers[0]["kind"] == "quest"


def test_build_stats_marker_from_way_geom() -> None:
    way = _enriched_way()
    stats = build_stats(_make_source_result([way]))
    markers = stats["markers"]
    assert len(markers) == 1
    # centroid of [[49.001, -122.501], [49.002, -122.502]]
    assert math.isclose(markers[0]["lat"], 49.0015, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(markers[0]["lon"], -122.5015, rel_tol=0.0, abs_tol=1e-9)


def test_build_stats_excludes_unmappable_elements() -> None:
    # Element with no lat/lon and no geom
    bare: dict[str, Any] = {
        "type": "way",
        "id": 99,
        "timestamp": "",
        "user": "x",
        "uid": 1,
        "changeset": 1,
        "tags": {},
        "nodes": [],
        "kind": "quest",
        "category": "",
        "versions": [],
        "photos": [],
        "readable": {},
        "geom": None,
    }
    stats = build_stats(_make_source_result([bare]))
    assert stats["markers"] == []


def test_build_stats_note_marker_kind() -> None:
    note = _note_element()
    stats = build_stats(_make_source_result([note]))
    m = stats["markers"][0]
    assert m["kind"] == "note"
    assert m["text"] == "A field note"


def test_build_stats_marker_has_top_level_user_and_timestamp() -> None:
    """Notes have no version history; markers must carry user/timestamp at
    the top level so their author is never dropped from the popup."""
    note = _note_element(user="carol")
    stats = build_stats(_make_source_result([note]))
    m = stats["markers"][0]
    assert m["user"] == "carol"
    assert m["timestamp"] == "2026-01-20T20:30:00Z"
    assert m["versions"] == []


def test_build_stats_showcase_photos_url_passthrough() -> None:
    photos = [{"src": "https://example.com/img.jpg", "caption": "Test"}]
    stats = build_stats(_make_source_result(), showcase_photos=photos)
    assert stats["showcase_photos"][0]["src"] == "https://example.com/img.jpg"
    assert stats["showcase_photos"][0]["caption"] == "Test"


def test_build_stats_showcase_local_path_embedded_as_data_uri(tmp_path: Path) -> None:
    showcase_dir = tmp_path / "showcase"
    showcase_dir.mkdir()
    img_path = showcase_dir / "001.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # minimal JPEG-like bytes
    photos = [{"src": "showcase/001.jpg", "caption": "Volunteers"}]
    stats = build_stats(
        _make_source_result(), showcase_photos=photos, event_dir=tmp_path
    )
    assert stats["showcase_photos"][0]["src"].startswith("data:image/jpeg;base64,")
    assert stats["showcase_photos"][0]["caption"] == "Volunteers"


def test_build_stats_showcase_empty_without_photos() -> None:
    stats = build_stats(_make_source_result())
    assert stats["showcase_photos"] == []


def test_build_stats_media_features(tmp_path: Path) -> None:
    pictures_dir = tmp_path / "pictures"
    pictures_dir.mkdir()
    (pictures_dir / "002.png").write_bytes(b"png")
    (pictures_dir / "001.jpg").write_bytes(b"jpg")
    stats = build_stats(
        _make_source_result(),
        pictures="pictures",
        quotes=[
            {
                "quote": "A welcoming map.",
                "first_name": "Ada",
                "organization": "TDEI",
            }
        ],
        slideshow_url=["https://example.com/one.jpg", "https://example.com/two.jpg"],
        video_url="https://www.youtube.com/watch?v=abc123",
        event_dir=tmp_path,
    )
    assert [item["src"].split(",")[0] for item in stats["pictures"]] == [
        "data:image/jpeg;base64",
        "data:image/png;base64",
    ]
    assert stats["quotes"][0]["text"] == "A welcoming map."
    assert len(stats["slideshow_images"]) == 2
    assert stats["video_embed_url"] == "https://www.youtube.com/embed/abc123"
    assert stats["video_kind"] == "iframe"


def test_build_stats_marker_has_version_history() -> None:
    node = _enriched_node()
    stats = build_stats(_make_source_result([node]))
    m = stats["markers"][0]
    assert len(m["versions"]) == 1
    assert m["versions"][0]["action"] == "modify"
    assert m["versions"][0]["user"] == "alice"


# ---------------------------------------------------------------------------
# anonymize_stats
# ---------------------------------------------------------------------------


def test_anonymize_stats_redacts_names_consistently_without_mutating_input() -> None:
    stats: dict[str, Any] = {
        "contributors_breakdown": [
            {"user": "alice", "count": 2},
            {"user": "bob", "count": 1},
        ],
        "markers": [
            {
                "user": "alice",
                "text": "Alice added a note.",
                "versions": [{"user": "bob"}, {"user": "carol"}],
            }
        ],
        "quest_answer_log": [
            {
                "submitted_by": "alice",
                "answer": "Alice reported a crack.",
                "answer_value_json": json.dumps("Alice reported a crack."),
            }
        ],
        "quotes": [
            {
                "text": "Dana Reader volunteered.",
                "first_name": "Dana",
                "last_name": "Reader",
            }
        ],
    }

    anonymized = anonymize_stats(stats)

    assert anonymized["contributors_breakdown"] == [
        {"user": "Participant 1", "count": 2},
        {"user": "Participant 2", "count": 1},
    ]
    assert anonymized["markers"][0]["user"] == "Participant 1"
    assert anonymized["markers"][0]["versions"] == [
        {"user": "Participant 2"},
        {"user": "Participant 3"},
    ]
    assert anonymized["markers"][0]["text"] == "Participant 1 added a note."
    assert anonymized["quest_answer_log"][0]["submitted_by"] == "Participant 1"
    assert anonymized["quest_answer_log"][0]["answer"] == (
        "Participant 1 reported a crack."
    )
    assert (
        json.loads(anonymized["quest_answer_log"][0]["answer_value_json"])
        == "Participant 1 reported a crack."
    )
    assert anonymized["quotes"][0]["first_name"] == "Participant 4"
    assert anonymized["quotes"][0]["last_name"] == ""
    assert anonymized["quotes"][0]["text"] == "Participant 4 volunteered."
    assert stats["contributors_breakdown"][0]["user"] == "alice"
    assert stats["markers"][0]["user"] == "alice"
    assert stats["quest_answer_log"][0]["submitted_by"] == "alice"
    assert anonymize_stats(anonymized) == anonymized


# ---------------------------------------------------------------------------
# write_stats
# ---------------------------------------------------------------------------


def test_write_stats_creates_file(tmp_path: Path) -> None:
    stats = build_stats(_make_source_result())
    dest = write_stats(stats, tmp_path, "test-event", "walkabout")
    assert dest.exists()
    assert dest.name == "stats.json"
    assert dest.parent.name == "walkabout"


def test_write_stats_output_is_valid_json(tmp_path: Path) -> None:
    stats = build_stats(_make_source_result())
    dest = write_stats(stats, tmp_path, "test-event", "walkabout")
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["activity_id"] == "walkabout"


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


def _sample_stats() -> dict[str, Any]:
    elements = [
        _enriched_node(id_=1, user="alice", kind="quest", category="Sidewalks"),
        _enriched_node(id_=2, user="bob", kind="create", category="Crossings"),
        _note_element(),
    ]
    return build_stats(_make_source_result(elements))


def test_render_report_returns_html_string() -> None:
    config = _minimal_config()
    activity = config["activities"][0]
    html = render_report(_sample_stats(), config, activity)
    assert isinstance(html, str)
    assert len(html) > 500


def test_render_report_html_lang_en() -> None:
    """WCAG 3.1.1 — html element must have lang=en (S1)."""
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert '<html lang="en">' in html


def test_render_report_single_h1() -> None:
    """One <h1> per page (S2)."""
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert html.count("<h1") == 1


def test_render_report_title_in_title_tag() -> None:
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    assert "<title>Test Event</title>" in html


def test_render_report_title_in_h1() -> None:
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    assert "Test Event" in html


def test_render_report_subtitle_present() -> None:
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    assert "January 20, 2026" in html


def test_render_report_subtitle_uses_human_readable_date() -> None:
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    assert "January 20, 2026" in html


def test_render_report_activity_label_in_h2() -> None:
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    assert "Test Walk/Roll" in html


def test_render_report_report_title_override() -> None:
    config = _minimal_config()
    config["report"] = {"title": "Custom Report Title"}
    html = render_report(_sample_stats(), config, config["activities"][0])
    assert "Custom Report Title" in html


@pytest.mark.parametrize(
    ("report_value", "event_name", "message"),
    [
        ("invalid", None, "config.report must be an object"),
        ({"title": 123}, None, "config.report.title must be a string"),
        ({"subtitle": 123}, None, "config.report.subtitle must be a string"),
        (None, 123, "config.name must be a string"),
    ],
)
def test_render_report_rejects_invalid_config_values(
    report_value: object,
    event_name: object | None,
    message: str,
) -> None:
    """Malformed report configuration fails with a clear error."""
    config = _minimal_config()
    if report_value is not None:
        config["report"] = report_value
    if event_name is not None:
        config["name"] = event_name
    with pytest.raises(TypeError, match=message):
        render_report(_sample_stats(), config, config["activities"][0])


def test_render_report_changeset_badge_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "changeset" in html


def test_render_report_note_badge_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "note" in html


def test_render_report_stats_json_inlined() -> None:
    """The report embeds hostile stats as safe, valid JSON."""
    payload = "<script>alert(1)</script> &"
    stats = _sample_stats()
    stats["untrusted_text"] = payload
    config = _minimal_config()
    html = render_report(stats, config, config["activities"][0])

    json_start = html.index("const STATS = ") + len("const STATS = ")
    embedded_stats, json_length = json.JSONDecoder().raw_decode(html[json_start:])
    assert isinstance(embedded_stats, dict)
    assert embedded_stats["untrusted_text"] == payload

    serialized_stats = html[json_start : json_start + json_length]
    assert "<" not in serialized_stats
    assert ">" not in serialized_stats
    assert "&" not in serialized_stats
    assert r"\u003cscript\u003e" in serialized_stats
    assert r"\u0026" in serialized_stats


def test_render_report_quest_types_card_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "Quest Types" in html


def test_render_report_features_created_card_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "Features Created" in html


def test_render_report_contributors_card_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "Contributors" in html


def test_render_report_metric_card_accent_spans_full_height() -> None:
    html = render_report(
        _sample_stats(),
        _minimal_config(),
        _minimal_config()["activities"][0],
        template_dir=Path(__file__).resolve().parents[2] / "templates",
    )
    accent_rule = re.search(r"\.metric-card::before\s*\{([^}]*)\}", html)

    assert accent_rule is not None
    assert re.search(r"\binset:\s*0\s+auto\s+0\s+0;", accent_rule.group(1))


def test_render_report_questions_answered_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "Questions Answered" in html


def test_render_report_breakdowns_use_reference_tables() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert 'class="breakdown-table"' in html
    assert 'class="question-table"' in html
    assert "Times answered" in html


def test_render_report_showcase_section_absent_when_no_photos() -> None:
    stats = build_stats(_make_source_result())  # no showcase
    html = render_report(stats, _minimal_config(), _minimal_config()["activities"][0])
    assert 'class="showcase"' not in html


def test_render_report_showcase_section_present_with_photos() -> None:
    photos = [{"src": "https://example.com/img.jpg", "caption": "Test"}]
    stats = build_stats(_make_source_result(), showcase_photos=photos)
    html = render_report(stats, _minimal_config(), _minimal_config()["activities"][0])
    assert "showcase" in html
    assert "https://example.com/img.jpg" in html


def test_render_report_media_sections_present() -> None:
    stats = build_stats(
        _make_source_result(),
        quotes=[{"text": "A quote.", "last_name": "Mapper"}],
        slideshow_url=["https://example.com/slide.jpg"],
        video_url="https://example.com/video.mp4",
    )
    html = render_report(stats, _minimal_config(), _minimal_config()["activities"][0])
    assert "Pictures" not in html
    assert "A quote." in html
    assert "Slideshow" in html
    assert "https://example.com/slide.jpg" in html
    assert "Video" in html
    assert "https://example.com/video.mp4" in html


def test_render_report_photo_modal_dialog_present() -> None:
    """Photo modal must use <dialog> for native focus trap (K3)."""
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "<dialog" in html
    assert "photo-modal" in html


def test_render_report_map_container_present() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert 'id="map"' in html


def test_render_report_resize_handle_is_prominent_and_accessible() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    handle_rule = re.search(r"\.map-resize-handle\s*\{([^}]*)\}", html)
    grip_rule = re.search(r"\.map-resize-handle::before\s*\{([^}]*)\}", html)

    assert handle_rule is not None
    assert "width: 6rem;" in handle_rule.group(1)
    assert "height: 1.75rem;" in handle_rule.group(1)
    assert "border: 1px solid var(--mm-border);" in handle_rule.group(1)
    assert "color-mix(in srgb, var(--mm-surface-strong) 82%, transparent)" in (
        handle_rule.group(1)
    )
    assert grip_rule is not None
    assert "width: 3rem;" in grip_rule.group(1)
    assert "height: 0.3rem;" in grip_rule.group(1)
    assert 'role="separator"' in html
    assert 'aria-orientation="horizontal"' in html
    assert 'tabindex="0"' in html
    assert ".map-resize-handle:active," in html
    assert ".map-resize-handle:focus-visible" in html


def test_render_report_markers_use_maplibre_layers_and_open_popups() -> None:
    """Keep activity markers attached to map rendering and hit testing."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])

    assert "new maplibregl.Marker(" not in html
    assert "type: 'FeatureCollection'" in html
    assert "type: 'geojson'" in html
    assert "map.addSource(markerSourceId, {" in html
    assert "data: markerFeatures" in html
    assert "source: markerSourceId" in html
    assert "map.addLayer({" in html
    assert "coordinates: [marker.lon, marker.lat]" in html
    assert "type: 'circle'" in html
    assert "type: 'symbol'" in html
    assert "map.on('style.load', function () {" in html
    assert "addMarkerLayers(markerFeatures);" in html
    circle_stroke_color = re.search(r"'circle-stroke-color':\s*(\[[^\]]+\])", html)
    icon_halo_color = re.search(r"'icon-halo-color':\s*(\[[^\]]+\])", html)
    assert circle_stroke_color is not None
    assert icon_halo_color is not None
    assert re.sub(r"\s+", "", circle_stroke_color.group(1)) == re.sub(
        r"\s+", "", icon_halo_color.group(1)
    )
    assert "map.queryRenderedFeatures(point, { layers: layers })" in html
    assert "map.on('click', function (event) {" in html
    assert "var feature = markerFeatureAt(event.point);" in html
    assert "if (marker) openMarkerPopup(marker);" in html


def test_render_report_contributor_rows_focus_matching_markers() -> None:
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )

    assert "data-contributor-table" in html
    assert 'data-contributor-user="alice"' in html
    assert 'aria-label="Show map contributions by alice"' in html
    assert "contributorTable.addEventListener('click'" in html
    assert "function markerHasContributor(marker, user)" in html
    assert "marker.versions.some(function (version)" in html
    assert "contributorSelected" in html
    assert "--mm-contributor-highlight" in html
    assert "map.fitBounds(bounds, { padding: 48, maxZoom: 14 });" in html


def test_render_report_popup_scrolls_inside_its_surface() -> None:
    """Keep long marker popup content scrolling inside one background surface."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    popup_surface_rules = re.findall(r"\.maplibregl-popup-content\s*\{([^}]*)\}", html)
    popup_content_rules = re.findall(r"\.mm-popup\s*\{([^}]*)\}", html)

    assert any("overflow: hidden;" in rule for rule in popup_surface_rules)
    assert not any("overflow-y: auto;" in rule for rule in popup_surface_rules)
    assert any(
        "max-height: 420px;" in rule and "overflow-y: auto;" in rule
        for rule in popup_content_rules
    )


def test_render_report_popup_close_button_has_scrollbar_clearance() -> None:
    """Keep the padded close button clear of the popup scrollbar."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    close_button_rules = re.findall(
        r"\.maplibregl-popup-close-button\s*\{([^}]*)\}", html
    )
    popup_header_rules = re.findall(r"\.mm-popup-header\s*\{([^}]*)\}", html)

    assert any(
        "right: 1.25rem;" in rule
        and "width: 1.75rem;" in rule
        and "height: 1.75rem;" in rule
        and "padding: 0.25rem;" in rule
        for rule in close_button_rules
    )
    assert any(
        "padding: 0.5rem 3.5rem 0.375rem 0.75rem;" in rule
        for rule in popup_header_rules
    )


def test_render_report_marker_controls_are_keyboard_accessible() -> None:
    """Keep marker locations available as labelled, keyboard-focusable buttons."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])

    assert 'id="map-marker-controls" class="sr-only" role="group"' in html
    assert "var control = document.createElement('button');" in html
    assert "control.setAttribute('aria-label', markerAriaLabel(marker));" in html
    assert "control.addEventListener('focus', function () {" in html
    assert "map.easeTo({ center: [marker.lon, marker.lat], duration: 250 });" in html
    assert "control.addEventListener('click', function () {" in html
    assert "openMarkerPopup(marker);" in html


def test_render_report_theme_toggle_uses_tcat_palette() -> None:
    """Expose an accessible theme toggle with the TCAT Wiki brand colors."""
    html = render_report(
        _sample_stats(),
        _minimal_config(),
        _minimal_config()["activities"][0],
        template_dir=Path(__file__).resolve().parents[2] / "templates",
    )
    normalized_html = re.sub(r"\s+", " ", html)

    assert 'id="theme-toggle"' in html
    assert 'aria-pressed="false"' in html
    assert "--mm-accent: #4b2e83;" in html
    assert "--mm-brand-gold: #b7a57a;" in html
    assert "--mm-accent: #c9b882;" in html
    assert "prefers-color-scheme: dark" in html
    assert "mapping-momentum-theme" in html
    assert ".map-wrapper .maplibregl-ctrl-group" in html
    assert "background: var(--mm-surface-strong);" in html
    assert "button + button" in html
    assert "border-top-color: var(--mm-border);" in html
    assert (
        ':root[data-theme="dark"] .map-wrapper .maplibregl-ctrl-group '
        ".maplibregl-ctrl-icon"
    ) in normalized_html
    assert "filter: invert(1);" in html
    assert re.search(
        r"""theme\s*===\s*["']dark["']\s*\?\s*["']fiord["']\s*:\s*["']positron["']""",
        html,
    )
    assert "syncMapStyle(root.dataset.theme);" in html
    assert "syncMapStyle(nextTheme);" in html


def test_render_report_has_accessible_export_button() -> None:
    """Expose a labeled export button with a decorative download icon."""
    html = render_report(
        _sample_stats(),
        _minimal_config(),
        _minimal_config()["activities"][0],
    )

    assert re.search(
        r'<button type="button"\s+class="report-export-button"',
        html,
    )
    assert "data-export-report" in html
    assert 'data-export-filename="test-event-walkabout-report.html"' in html
    assert 'aria-label="Export the complete report"' in html
    assert (
        '<svg class="report-export-icon" aria-hidden="true" focusable="false"' in html
    )
    assert "<span>Export</span>" in html
    assert html.index('class="report-export-icon"') < html.index("<span>Export</span>")
    assert "URL.createObjectURL(blob)" in html
    assert re.search(
        r"link\.download\s*=\s*exportButton\.dataset\.exportFilename",
        html,
    )


def test_render_report_exposes_openfreemap_basemap_styles() -> None:
    """Expose the reference's five OpenFreeMap styles to report viewers."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    styles = ["positron", "bright", "liberty", "dark", "fiord"]

    assert '<select id="map-style" aria-label="Basemap style">' in html
    assert '<option value="positron" selected>Positron</option>' in html
    assert html.count("<option value=") == len(styles)
    for style in styles:
        assert f"https://tiles.openfreemap.org/styles/{style}" in html
    assert "map.setStyle(styleUrl, { diff: false });" in html
    assert "if (activeGeom) addGeomLayer(activeGeom);" in html


def test_render_report_map_legend_is_open_and_title_case() -> None:
    """Render the map legend expanded with its title-case label."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])

    assert '<details class="map-legend" open>' in html
    assert "<summary>Map Legend</summary>" in html


def test_render_report_has_expected_map_attribution() -> None:
    """Render the requested data and map provider attribution."""
    config = _minimal_config()
    html = render_report(_sample_stats(), config, config["activities"][0])
    normalized_html = " ".join(html.split())
    expected_attribution = (
        'Data: <a href="https://workspaces.sidewalks.washington.edu/" '
        'target="_blank" rel="noopener noreferrer">TDEI Workspaces</a> '
        'contributors | Map: <a href="https://openfreemap.org" '
        'target="_blank" rel="noopener noreferrer">OpenFreeMap</a> • '
        '<a href="https://www.openmaptiles.org/" target="_blank" '
        'rel="noopener noreferrer">© OpenMapTiles</a> • '
        '<a href="https://www.openstreetmap.org/copyright" '
        'target="_blank" rel="noopener noreferrer">'
        "© OpenStreetMap contributors</a>"
    )

    assert expected_attribution in normalized_html
    assert "© Workspace contributors" not in html
    assert "new maplibregl.AttributionControl(" not in html
    attribution_style = re.search(
        r"\.map-attribution\s*\{([^}]+)\}",
        html,
    )
    assert attribution_style is not None
    assert "right: 0.4rem;" in attribution_style.group(1)
    assert "bottom: 0.2rem;" in attribution_style.group(1)
    assert "white-space: nowrap;" in attribution_style.group(1)


def test_render_report_skip_link_present() -> None:
    """Skip link must be the first focusable element (K4)."""
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "skip-link" in html
    assert "#main-content" in html


def test_render_report_map_expand_button_has_aria_label() -> None:
    """Icon-only map expand button must have aria-label (A6)."""
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "Expand map to full screen" in html


def test_render_report_modal_close_button_has_aria_label() -> None:
    """Icon-only close button must have aria-label (A6)."""
    html = render_report(
        _sample_stats(), _minimal_config(), _minimal_config()["activities"][0]
    )
    assert "Close photo gallery" in html


def test_render_report_empty_stats_no_crash() -> None:
    """Rendering with empty/minimal stats must not raise."""
    stats: dict[str, Any] = {
        "activity_id": "walkabout",
        "source_type": "workspace",
        "window_start": "2026-01-20T18:00:00+00:00",
        "window_end": "2026-01-21T04:00:00+00:00",
        "changeset_count": 0,
        "note_count": 0,
        "markers": [],
        "showcase_photos": [],
        "quest_type_breakdown": [],
        "features_created": [],
        "contributors_breakdown": [],
        "questions_answered": [],
    }
    html = render_report(stats, _minimal_config(), _minimal_config()["activities"][0])
    assert "<h1>" in html


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


def test_write_report_creates_file(tmp_path: Path) -> None:
    html = "<html><body>test</body></html>"
    dest = write_report(html, tmp_path, "test-event", "walkabout")
    assert dest.exists()
    assert dest.name == "index.html"
    assert dest.parent.name == "walkabout"


def test_write_report_content_correct(tmp_path: Path) -> None:
    html = "<html><body>hello world</body></html>"
    dest = write_report(html, tmp_path, "test-event", "walkabout")
    assert "hello world" in dest.read_text(encoding="utf-8")


def test_write_report_replaces_existing_file(tmp_path: Path) -> None:
    dest = write_report("first", tmp_path, "test-event", "walkabout")
    replacement = write_report("second", tmp_path, "test-event", "walkabout")
    assert replacement == dest
    assert replacement.read_text(encoding="utf-8") == "second"
