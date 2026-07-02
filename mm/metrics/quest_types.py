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

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict:
    """Compute ``quest_type_breakdown``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Uses ``kind``, ``category``, and ``photos`` on each element.

    Returns
    -------
    dict
        ``{"quest_type_breakdown": [{"category": str, "count": int, "photo_count": int}, …]}``
    """
    counts: Counter[str] = Counter()
    photo_counts: Counter[str] = Counter()

    for elem in elements:
        if elem.get("kind") == "note":
            continue
        category: str = elem.get("category", "")
        counts[category] += 1
        photo_counts[category] += len(elem.get("photos", []))

    breakdown = [
        {
            "category": category,
            "count": count,
            "photo_count": photo_counts[category],
        }
        for category, count in counts.most_common()
    ]
    return {"quest_type_breakdown": breakdown}
