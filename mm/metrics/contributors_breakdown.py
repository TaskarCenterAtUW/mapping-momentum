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
from collections.abc import Mapping, Sequence, Sized
from typing import TypedDict

from mm.metrics.base import register


class ContributorBreakdown(TypedDict):
    """Counts for one contributor."""

    user: str
    count: int
    photo_count: int


@register("workspace")
def compute(
    elements: Sequence[Mapping[str, object]],
) -> dict[str, list[ContributorBreakdown]]:
    """Compute ``contributors_breakdown``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Uses ``kind``, ``user``, and ``photos`` on each element.

    Returns
    -------
    dict
        ``{"contributors_breakdown": [{"user": str, "count": int,``
        ``"photo_count": int}, …]}``
    """
    counts: Counter[str] = Counter()
    photo_counts: Counter[str] = Counter()

    for elem in elements:
        user = elem.get("user", "")
        if not user:
            continue
        if not isinstance(user, str):
            raise TypeError("element user must be a string")
        photos = elem.get("photos", [])
        if not isinstance(photos, Sized):
            raise TypeError("element photos must have a length")
        counts[user] += 1
        photo_counts[user] += len(photos)

    breakdown: list[ContributorBreakdown] = [
        {
            "user": user,
            "count": count,
            "photo_count": photo_counts[user],
        }
        for user, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"contributors_breakdown": breakdown}
