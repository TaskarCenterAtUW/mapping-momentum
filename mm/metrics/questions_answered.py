"""
mm.metrics.questions_answered — per-category question-answer distribution metric.

Registered for ``workspace`` source type.

Metric key produced
-------------------
questions_answered : list[dict]
    One entry per category, sorted by category name.  Only categories
    with at least one answered question are included.

    Each entry::

        {
            "category": str,   # e.g. "Sidewalks"
            "total":    int,   # total answer counts across all questions in this category
            "questions": [
                {
                    "tag":            str,        # OSM tag key, e.g. "ext:surface"
                    "label":          str,        # human-readable question title
                                                  # (falls back to tag key when no
                                                  # quest definition is available)
                    "times_answered": int,        # elements that have a value for this tag
                    "choices": [
                        {
                            "value": str,   # raw OSM tag value, e.g. "asphalt"
                            "label": str,   # decoded choice text, e.g. "Asphalt"
                            "count": int,   # elements with this value
                        },
                        ...
                    ],
                },
                ...
            ],
        }

Algorithm
---------
The metric uses two fields already present on enriched elements:

- ``element["readable"]``  — ``{tag: decoded_label}`` for the element's current
  tag values.  Only quest-tagged keys with discrete choices are present here
  (TextEntry and Numeric quests are absent).  The decoded label IS the choice
  text for that element's value, so no external quest definition is required to
  build the choice-label table.

- ``element["category"]``  — element-level category string from the quest definition.
  Used to group questions by category.

An optional ``quest_def`` parameter (keyword-only) enables enriched question
titles.  Without it, the tag key is used as the question label.

Notes
-----
- Note elements (``kind == "note"``) are excluded.
- Elements without ``readable`` or with an empty ``readable`` dict contribute
  nothing to this metric.
- The output is deterministic: categories, questions, and choices are all sorted
  alphabetically by their key/value.
"""

from __future__ import annotations

from typing import Any

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict], *, quest_def: Any = None) -> dict:
    """Compute ``questions_answered``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Uses ``kind``, ``category``, ``tags``, and ``readable`` on each element.
    quest_def:
        Optional :class:`~mm.quests.loader.QuestDefinition`.  When provided,
        ``tag_to_title`` is used to supply human-readable question labels.
        When ``None``, the tag key is used as the label.

    Returns
    -------
    dict
        ``{"questions_answered": [<category_entry>, …]}``
    """
    # category → tag → {"times_answered": int, "choices": {value: {"label": str, "count": int}}}
    data: dict[str, dict[str, Any]] = {}

    for elem in elements:
        if elem.get("kind") == "note":
            continue

        category: str = elem.get("category", "")
        tags: dict[str, str] = elem.get("tags", {})
        readable: dict[str, str] = elem.get("readable", {})

        for tag, decoded_label in readable.items():
            raw_value = tags.get(tag)
            if not raw_value:
                continue

            tag_data = data.setdefault(category, {}).setdefault(
                tag, {"times_answered": 0, "choices": {}}
            )
            tag_data["times_answered"] += 1

            if raw_value not in tag_data["choices"]:
                tag_data["choices"][raw_value] = {
                    "label": decoded_label, "count": 0}
            tag_data["choices"][raw_value]["count"] += 1

    result = []
    for category in sorted(data):
        tags_data = data[category]
        total = sum(td["times_answered"] for td in tags_data.values())
        questions = []
        for tag in sorted(tags_data):
            td = tags_data[tag]
            label = (
                quest_def.tag_to_title.get(
                    tag, tag) if quest_def is not None else tag
            )
            choices = [
                {"value": v, "label": info["label"], "count": info["count"]}
                for v, info in sorted(td["choices"].items())
            ]
            questions.append(
                {
                    "tag": tag,
                    "label": label,
                    "times_answered": td["times_answered"],
                    "choices": choices,
                }
            )
        result.append(
            {"category": category, "total": total, "questions": questions})

    return {"questions_answered": result}
