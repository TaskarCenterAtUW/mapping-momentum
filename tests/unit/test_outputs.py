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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from mm.outputs.html_report import _safe_json, render_report, write_report
from mm.outputs.json_stats import build_stats, write_stats
from mm.sources.base import SourceResult

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_source_result(elements: list[dict] | None = None) -> SourceResult:
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
    tags: dict | None = None,
    readable: dict | None = None,
    photos: list | None = None,
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


def _minimal_config(*, showcase: list | None = None) -> dict[str, Any]:
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
    assert markers[0]["lat"] == pytest.approx(49.001)
    assert markers[0]["lon"] == pytest.approx(-122.501)
    assert markers[0]["kind"] == "quest"


def test_build_stats_marker_from_way_geom() -> None:
    way = _enriched_way()
    stats = build_stats(_make_source_result([way]))
    markers = stats["markers"]
    assert len(markers) == 1
    # centroid of [[49.001, -122.501], [49.002, -122.502]]
    assert markers[0]["lat"] == pytest.approx(49.0015)
    assert markers[0]["lon"] == pytest.approx(-122.5015)


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


def test_build_stats_marker_has_version_history() -> None:
    node = _enriched_node()
    stats = build_stats(_make_source_result([node]))
    m = stats["markers"][0]
    assert len(m["versions"]) == 1
    assert m["versions"][0]["action"] == "modify"
    assert m["versions"][0]["user"] == "alice"


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
# _safe_json
# ---------------------------------------------------------------------------


def test_safe_json_escapes_angle_brackets() -> None:
    result = _safe_json({"k": "<script>alert(1)</script>"})
    assert "<script>" not in result
    assert "\\u003cscript\\u003e" in result


def test_safe_json_escapes_ampersand() -> None:
    result = _safe_json({"k": "a & b"})
    assert "&" not in result or "\\u0026" in result


def test_safe_json_valid_json() -> None:
    data = {"a": 1, "b": [1, 2], "c": True, "d": None}
    parsed = json.loads(_safe_json(data))
    assert parsed["a"] == 1
    assert parsed["c"] is True


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
    """stats_json must be inlined without raw < or > (XSS prevention)."""
    stats = _sample_stats()
    html = render_report(stats, _minimal_config(), _minimal_config()["activities"][0])
    assert "const STATS" in html
    # Verify that _safe_json was applied: no raw < in the STATS block
    script_start = html.index("const STATS")
    script_end = html.index("</script>", script_start)
    script_block = html[script_start:script_end]
    assert "<" not in script_block


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
