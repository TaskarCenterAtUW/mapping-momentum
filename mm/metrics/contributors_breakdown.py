"""
mm.metrics.contributors_breakdown — per-contributor breakdown metric.

Registered for ``workspace`` source type.

Metric key produced
-------------------
contributors_breakdown : list[dict]
    One entry per mapper who contributed at least one element (quest, create,
    or note).  Note authors are included because adding a field note is an
    active form of participation.
    Entries are sorted by ``count`` descending (highest contributor first).

    Each entry::

        {
            "user":        str,   # OSM username
            "count":       int,   # total elements (any kind) by this user
            "photo_count": int,   # total KartaView photos taken by this user
        }
"""

from __future__ import annotations

from collections import Counter

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict:
    """Compute ``contributors_breakdown``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Uses ``kind``, ``user``, and ``photos`` on each element.

    Returns
    -------
    dict
        ``{"contributors_breakdown": [{"user": str, "count": int, "photo_count": int}, …]}``
    """
    counts: Counter[str] = Counter()
    photo_counts: Counter[str] = Counter()

    for elem in elements:
        user: str = elem.get("user", "")
        counts[user] += 1
        photo_counts[user] += len(elem.get("photos", []))

    breakdown = [
        {
            "user": user,
            "count": count,
            "photo_count": photo_counts[user],
        }
        for user, count in counts.most_common()
    ]
    return {"contributors_breakdown": breakdown}
