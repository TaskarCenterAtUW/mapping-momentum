"""
mm.metrics.contributor_count — count of unique OSM contributors.

Registered for ``workspace`` source type.

Metric key produced
-------------------
contributor_count : int
    Number of distinct OSM usernames (``user`` field) across all
    elements in the filtered set.  Reflects unique mappers who
    touched at least one element during the event window.
"""

from __future__ import annotations

from typing import Any

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict[str, Any]]) -> dict[str, int | float]:
    """Compute ``contributor_count``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int | float]
        ``{"contributor_count": <int>}``
    """
    contributor_count = len({e["user"] for e in elements if e.get("user")})
    return {"contributor_count": contributor_count}
