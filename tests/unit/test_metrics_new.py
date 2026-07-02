"""Unit tests for the Slice D metric modules:
  notes, quest_types, contributors_breakdown, features_created, questions_answered.

All tests are fully offline — no network calls, no file I/O.

Test matrix
-----------
note_count:
  - empty list → 0
  - no note elements → 0
  - only notes → correct count
  - mixed elements → counts only kind=="note"

quest_type_breakdown:
  - empty list → empty list
  - note elements excluded
  - entries grouped by category
  - count and photo_count correct
  - sorted by count descending
  - unknown category ("") is included as a distinct group
  - single category

contributors_breakdown:
  - empty list → empty list
  - note authors included (notes count as participation)
  - entries grouped by user
  - count and photo_count correct
  - sorted by count descending
  - tie in count preserves consistent order (Counter.most_common)

features_created:
  - empty list → empty list
  - only kind=="create" elements counted
  - grouped by type (node/way/relation)
  - sorted by count descending
  - note elements excluded (notes have kind=="note", not "create")
  - quest elements excluded (kind=="quest")

questions_answered:
  - empty list → empty list
  - note elements excluded
  - entries grouped by category
  - total is sum of all times_answered in that category
  - times_answered is count of elements with each tag
  - choices have value, label, count
  - choice labels come from element["readable"]
  - choice counts aggregated across elements
  - without quest_def: tag key used as question label
  - with quest_def: quest title used as question label
  - elements with empty readable contribute nothing
  - TextEntry / Numeric keys absent from readable → excluded
  - categories sorted alphabetically
  - questions sorted alphabetically by tag within category
  - choices sorted alphabetically by value
"""

from __future__ import annotations

from typing import Any

import mm.metrics.contributors_breakdown as contributors_mod
import mm.metrics.features_created as features_mod
import mm.metrics.notes as notes_mod
import mm.metrics.quest_types as quest_types_mod
import mm.metrics.questions_answered as questions_mod

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


def _elem(
    *,
    id_: int = 1,
    type_: str = "node",
    user: str = "alice",
    kind: str = "quest",
    category: str = "Sidewalks",
    tags: dict | None = None,
    readable: dict | None = None,
    photos: list | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "id": id_,
        "timestamp": "2026-01-20T20:00:00Z",
        "user": user,
        "uid": 10,
        "changeset": 100,
        "tags": tags or {},
        "kind": kind,
        "category": category,
        "versions": [],
        "photos": photos or [],
        "readable": readable or {},
        "geom": None,
    }


def _note(id_: int = 99, user: str = "carol") -> dict[str, Any]:
    return {
        "type": "note",
        "id": id_,
        "timestamp": "2026-01-20T20:30:00Z",
        "user": user,
        "uid": 12,
        "changeset": 0,
        "tags": {},
        "kind": "note",
        "category": "",
        "versions": [],
        "photos": [],
        "readable": {},
        "geom": None,
        "lat": 49.0,
        "lon": -122.5,
        "text": "A field note",
    }


# Minimal quest definition stub
class _FakeQuestDef:
    tag_to_title = {
        "ext:surface": "What is this sidewalk's surface type?",
        "ext:crossing_markings": "Does this crossing have markings?",
    }


_QUEST_DEF = _FakeQuestDef()

# A representative set of enriched elements used across multiple tests:
#   elem 1 — Sidewalks / quest / alice / ext:surface=asphalt / 1 photo
#   elem 2 — Sidewalks / quest / alice / ext:surface=concrete / 0 photos
#   elem 3 — Sidewalks / create / bob / ext:surface=asphalt / 0 photos  (way)
#   elem 4 — Crossings / quest / bob / ext:crossing_markings=yes / 1 photo
#   elem 5 — (note)
#   elem 6 — Crossings / create / alice / ext:crossing_markings=no / 0 photos

_ELEMENTS: list[dict[str, Any]] = [
    _elem(
        id_=1,
        type_="node",
        user="alice",
        kind="quest",
        category="Sidewalks",
        tags={"ext:surface": "asphalt"},
        readable={"ext:surface": "Asphalt"},
        photos=["https://cdn.kartaview.org/photo1.jpg"],
    ),
    _elem(
        id_=2,
        type_="node",
        user="alice",
        kind="quest",
        category="Sidewalks",
        tags={"ext:surface": "concrete"},
        readable={"ext:surface": "Concrete"},
        photos=[],
    ),
    _elem(
        id_=3,
        type_="way",
        user="bob",
        kind="create",
        category="Sidewalks",
        tags={"ext:surface": "asphalt"},
        readable={"ext:surface": "Asphalt"},
        photos=[],
    ),
    _elem(
        id_=4,
        type_="node",
        user="bob",
        kind="quest",
        category="Crossings",
        tags={"ext:crossing_markings": "yes"},
        readable={"ext:crossing_markings": "Yes"},
        photos=["https://cdn.kartaview.org/photo2.jpg"],
    ),
    _note(id_=5, user="carol"),
    _elem(
        id_=6,
        type_="node",
        user="alice",
        kind="create",
        category="Crossings",
        tags={"ext:crossing_markings": "no"},
        readable={"ext:crossing_markings": "No"},
        photos=[],
    ),
]


# ---------------------------------------------------------------------------
# note_count
# ---------------------------------------------------------------------------


def test_note_count_empty() -> None:
    assert notes_mod.compute([]) == {"note_count": 0}


def test_note_count_no_notes() -> None:
    elements = [_elem(id_=1), _elem(id_=2)]
    assert notes_mod.compute(elements) == {"note_count": 0}


def test_note_count_only_notes() -> None:
    elements = [_note(1), _note(2), _note(3)]
    assert notes_mod.compute(elements) == {"note_count": 3}


def test_note_count_mixed() -> None:
    elements = [_elem(id_=1), _note(2), _elem(id_=3), _note(4)]
    assert notes_mod.compute(elements) == {"note_count": 2}


def test_note_count_full_fixture() -> None:
    assert notes_mod.compute(_ELEMENTS) == {"note_count": 1}


# ---------------------------------------------------------------------------
# quest_type_breakdown
# ---------------------------------------------------------------------------


def test_quest_types_empty() -> None:
    result = quest_types_mod.compute([])
    assert result == {"quest_type_breakdown": []}


def test_quest_types_excludes_notes() -> None:
    elements = [_note(), _note()]
    result = quest_types_mod.compute(elements)
    assert result["quest_type_breakdown"] == []


def test_quest_types_groups_by_category() -> None:
    result = quest_types_mod.compute(_ELEMENTS)
    categories = [e["category"] for e in result["quest_type_breakdown"]]
    assert "Sidewalks" in categories
    assert "Crossings" in categories


def test_quest_types_count_correct() -> None:
    result = quest_types_mod.compute(_ELEMENTS)
    by_cat = {e["category"]: e for e in result["quest_type_breakdown"]}
    # Sidewalks: elems 1, 2, 3 → count=3
    assert by_cat["Sidewalks"]["count"] == 3
    # Crossings: elems 4, 6 → count=2
    assert by_cat["Crossings"]["count"] == 2


def test_quest_types_photo_count_correct() -> None:
    result = quest_types_mod.compute(_ELEMENTS)
    by_cat = {e["category"]: e for e in result["quest_type_breakdown"]}
    # elem 1 has 1 photo (Sidewalks)
    assert by_cat["Sidewalks"]["photo_count"] == 1
    # elem 4 has 1 photo (Crossings)
    assert by_cat["Crossings"]["photo_count"] == 1


def test_quest_types_sorted_by_count_descending() -> None:
    result = quest_types_mod.compute(_ELEMENTS)
    counts = [e["count"] for e in result["quest_type_breakdown"]]
    assert counts == sorted(counts, reverse=True)


def test_quest_types_single_category() -> None:
    elements = [_elem(id_=i, category="Kerbs") for i in range(3)]
    result = quest_types_mod.compute(elements)
    assert len(result["quest_type_breakdown"]) == 1
    assert result["quest_type_breakdown"][0] == {
        "category": "Kerbs",
        "count": 3,
        "photo_count": 0,
    }


def test_quest_types_unknown_category_included() -> None:
    elements = [_elem(id_=1, category=""), _elem(id_=2, category="Kerbs")]
    result = quest_types_mod.compute(elements)
    categories = {e["category"] for e in result["quest_type_breakdown"]}
    assert "" in categories
    assert "Kerbs" in categories


# ---------------------------------------------------------------------------
# contributors_breakdown
# ---------------------------------------------------------------------------


def test_contributors_empty() -> None:
    result = contributors_mod.compute([])
    assert result == {"contributors_breakdown": []}


def test_contributors_includes_note_authors() -> None:
    elements = [_note(id_=1, user="carol"), _note(id_=2, user="carol")]
    result = contributors_mod.compute(elements)
    by_user = {e["user"]: e for e in result["contributors_breakdown"]}
    assert "carol" in by_user
    assert by_user["carol"]["count"] == 2


def test_contributors_groups_by_user() -> None:
    result = contributors_mod.compute(_ELEMENTS)
    users = [e["user"] for e in result["contributors_breakdown"]]
    assert "alice" in users
    assert "bob" in users
    assert "carol" in users  # carol added a note — counts as a contribution


def test_contributors_count_correct() -> None:
    result = contributors_mod.compute(_ELEMENTS)
    by_user = {e["user"]: e for e in result["contributors_breakdown"]}
    # alice: elems 1, 2, 6 → count=3
    assert by_user["alice"]["count"] == 3
    # bob: elems 3, 4 → count=2
    assert by_user["bob"]["count"] == 2
    # carol: elem 5 (note) → count=1
    assert by_user["carol"]["count"] == 1


def test_contributors_photo_count_correct() -> None:
    result = contributors_mod.compute(_ELEMENTS)
    by_user = {e["user"]: e for e in result["contributors_breakdown"]}
    # alice has elem 1 with 1 photo
    assert by_user["alice"]["photo_count"] == 1
    # bob has elem 4 with 1 photo
    assert by_user["bob"]["photo_count"] == 1


def test_contributors_sorted_descending() -> None:
    result = contributors_mod.compute(_ELEMENTS)
    counts = [e["count"] for e in result["contributors_breakdown"]]
    assert counts == sorted(counts, reverse=True)


def test_contributors_single_user() -> None:
    elements = [_elem(id_=i, user="alice") for i in range(4)]
    result = contributors_mod.compute(elements)
    assert len(result["contributors_breakdown"]) == 1
    assert result["contributors_breakdown"][0] == {
        "user": "alice",
        "count": 4,
        "photo_count": 0,
    }


# ---------------------------------------------------------------------------
# features_created
# ---------------------------------------------------------------------------


def test_features_created_empty() -> None:
    result = features_mod.compute([])
    assert result == {"features_created": []}


def test_features_created_excludes_quest_elements() -> None:
    elements = [_elem(id_=1, kind="quest"), _elem(id_=2, kind="quest")]
    result = features_mod.compute(elements)
    assert result["features_created"] == []


def test_features_created_excludes_notes() -> None:
    result = features_mod.compute([_note()])
    assert result["features_created"] == []


def test_features_created_groups_by_type() -> None:
    result = features_mod.compute(_ELEMENTS)
    by_type = {e["feature_type"]: e for e in result["features_created"]}
    # elem 3 (way, create), elem 6 (node, create)
    assert "way" in by_type
    assert "node" in by_type


def test_features_created_count_correct() -> None:
    result = features_mod.compute(_ELEMENTS)
    by_type = {e["feature_type"]: e for e in result["features_created"]}
    assert by_type["way"]["count"] == 1  # elem 3
    assert by_type["node"]["count"] == 1  # elem 6


def test_features_created_sorted_descending() -> None:
    elements = [_elem(id_=i, kind="create", type_="node") for i in range(5)] + [
        _elem(id_=10 + i, kind="create", type_="way") for i in range(2)
    ]
    result = features_mod.compute(elements)
    counts = [e["count"] for e in result["features_created"]]
    assert counts == sorted(counts, reverse=True)


def test_features_created_only_create_elements() -> None:
    elements = [
        _elem(id_=1, kind="create", type_="node"),
        _elem(id_=2, kind="quest", type_="node"),
        _elem(id_=3, kind="create", type_="way"),
        _note(4),
    ]
    result = features_mod.compute(elements)
    total = sum(e["count"] for e in result["features_created"])
    assert total == 2


# ---------------------------------------------------------------------------
# questions_answered
# ---------------------------------------------------------------------------


def test_questions_answered_empty() -> None:
    result = questions_mod.compute([])
    assert result == {"questions_answered": []}


def test_questions_answered_excludes_notes() -> None:
    elements = [_note(), _note()]
    result = questions_mod.compute(elements)
    assert result["questions_answered"] == []


def test_questions_answered_excludes_empty_readable() -> None:
    elements = [_elem(id_=1, readable={}, tags={"ext:surface": "asphalt"})]
    result = questions_mod.compute(elements)
    assert result["questions_answered"] == []


def test_questions_answered_groups_by_category() -> None:
    result = questions_mod.compute(_ELEMENTS)
    categories = [e["category"] for e in result["questions_answered"]]
    assert "Sidewalks" in categories
    assert "Crossings" in categories


def test_questions_answered_total_correct() -> None:
    result = questions_mod.compute(_ELEMENTS)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    # Sidewalks: elems 1, 2, 3 each answer ext:surface → total=3
    assert by_cat["Sidewalks"]["total"] == 3
    # Crossings: elems 4, 6 each answer ext:crossing_markings → total=2
    assert by_cat["Crossings"]["total"] == 2


def test_questions_answered_times_answered_correct() -> None:
    result = questions_mod.compute(_ELEMENTS)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    sidewalk_q = {q["tag"]: q for q in by_cat["Sidewalks"]["questions"]}
    assert sidewalk_q["ext:surface"]["times_answered"] == 3


def test_questions_answered_choices_aggregated() -> None:
    result = questions_mod.compute(_ELEMENTS)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    sidewalk_q = {q["tag"]: q for q in by_cat["Sidewalks"]["questions"]}
    choices = {c["value"]: c for c in sidewalk_q["ext:surface"]["choices"]}
    # asphalt appears in elems 1 and 3 → count=2
    assert choices["asphalt"]["count"] == 2
    assert choices["asphalt"]["label"] == "Asphalt"
    # concrete appears in elem 2 → count=1
    assert choices["concrete"]["count"] == 1
    assert choices["concrete"]["label"] == "Concrete"


def test_questions_answered_choices_from_readable() -> None:
    """Choice labels come from element['readable'], not from quest_def."""
    elements = [
        _elem(
            id_=1,
            category="Kerbs",
            tags={"kerb": "lowered"},
            readable={"kerb": "Ramp"},  # non-obvious mapping
        )
    ]
    result = questions_mod.compute(elements)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    choices = {c["value"]: c for c in by_cat["Kerbs"]["questions"][0]["choices"]}
    assert choices["lowered"]["label"] == "Ramp"


def test_questions_answered_without_quest_def_uses_tag_as_label() -> None:
    result = questions_mod.compute(_ELEMENTS, quest_def=None)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    sidewalk_q = {q["tag"]: q for q in by_cat["Sidewalks"]["questions"]}
    # Without quest_def, label falls back to the tag key
    assert sidewalk_q["ext:surface"]["label"] == "ext:surface"


def test_questions_answered_with_quest_def_uses_title() -> None:
    result = questions_mod.compute(_ELEMENTS, quest_def=_QUEST_DEF)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    sidewalk_q = {q["tag"]: q for q in by_cat["Sidewalks"]["questions"]}
    assert sidewalk_q["ext:surface"]["label"] == "What is this sidewalk's surface type?"


def test_questions_answered_with_quest_def_unknown_tag_falls_back() -> None:
    elements = [
        _elem(
            id_=1,
            category="Misc",
            tags={"some:unknown:tag": "val"},
            readable={"some:unknown:tag": "Val"},
        )
    ]
    result = questions_mod.compute(elements, quest_def=_QUEST_DEF)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    q = by_cat["Misc"]["questions"][0]
    # Tag not in quest_def.tag_to_title → falls back to tag key
    assert q["label"] == "some:unknown:tag"


def test_questions_answered_categories_sorted() -> None:
    result = questions_mod.compute(_ELEMENTS)
    categories = [e["category"] for e in result["questions_answered"]]
    assert categories == sorted(categories)


def test_questions_answered_questions_sorted_by_tag() -> None:
    elements = [
        _elem(
            id_=1,
            category="Sidewalks",
            tags={"ext:z_tag": "a", "ext:a_tag": "b"},
            readable={"ext:z_tag": "A", "ext:a_tag": "B"},
        )
    ]
    result = questions_mod.compute(elements)
    tags = [q["tag"] for q in result["questions_answered"][0]["questions"]]
    assert tags == sorted(tags)


def test_questions_answered_choices_sorted_by_value() -> None:
    elements = [
        _elem(
            id_=1,
            category="Kerbs",
            tags={"kerb": "raised"},
            readable={"kerb": "Raised"},
        ),
        _elem(
            id_=2,
            category="Kerbs",
            tags={"kerb": "flush"},
            readable={"kerb": "Flush"},
        ),
        _elem(
            id_=3,
            category="Kerbs",
            tags={"kerb": "lowered"},
            readable={"kerb": "Ramp"},
        ),
    ]
    result = questions_mod.compute(elements)
    choices = result["questions_answered"][0]["questions"][0]["choices"]
    values = [c["value"] for c in choices]
    assert values == sorted(values)


def test_questions_answered_multiple_tags_per_element() -> None:
    elements = [
        _elem(
            id_=1,
            category="Sidewalks",
            tags={"ext:surface": "asphalt", "ext:obstruction": "no"},
            readable={"ext:surface": "Asphalt", "ext:obstruction": "No"},
        )
    ]
    result = questions_mod.compute(elements)
    by_cat = {e["category"]: e for e in result["questions_answered"]}
    assert by_cat["Sidewalks"]["total"] == 2
    tags = {q["tag"] for q in by_cat["Sidewalks"]["questions"]}
    assert "ext:surface" in tags
    assert "ext:obstruction" in tags
