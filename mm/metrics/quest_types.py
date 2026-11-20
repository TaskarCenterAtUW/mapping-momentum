"""
mm.metrics.quest_types — quest-type (category) breakdown metric.

Registered for ``workspace`` source type.

Metric key produced
-------------------
quest_type_breakdown : list[dict]
    One entry per category (``element_type`` from the quest definition).
    Entries are sorted by ``count`` descending.

    Each entry::

        {
            "category":    str,   # e.g. "Sidewalks", "Crossings"
            "count":       int,   # number of quest/create elements in this category
            "photo_count": int,   # total KartaView photos across those elements
        }

    Note elements (``kind == "note"``) are excluded from this breakdown;
    they are counted separately by ``notes.compute``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence, Sized
from typing import TypedDict

from mm.metrics.base import register


class QuestTypeCount(TypedDict):
    """Element and photo counts for one quest category."""

    category: str
    count: int
    photo_count: int


@register("workspace")
def compute(
    elements: Sequence[Mapping[str, object]],
) -> dict[str, list[QuestTypeCount]]:
    """Compute ``quest_type_breakdown``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Uses ``kind``, ``category``, and ``photos`` on each element.

    Returns
    -------
    dict[str, list[QuestTypeCount]]
        ``{"quest_type_breakdown": [{"category": str, "count": int,``
        ``"photo_count": int}, …]}``
    """
    counts: Counter[str] = Counter()
    photo_counts: Counter[str] = Counter()

    for elem in elements:
        if elem.get("kind") == "note":
            continue
        category = elem.get("category", "")
        if not isinstance(category, str):
            raise TypeError("element category must be a string")
        photos = elem.get("photos", [])
        if not isinstance(photos, Sized):
            raise TypeError("element photos must have a length")
        counts[category] += 1
        photo_counts[category] += len(photos)

    breakdown: list[QuestTypeCount] = [
        {
            "category": category,
            "count": count,
            "photo_count": photo_counts[category],
        }
        for category, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return {"quest_type_breakdown": breakdown}
