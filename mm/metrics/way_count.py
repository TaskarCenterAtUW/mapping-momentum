"""
mm.metrics.way_count — count of edited OSM ways.

Registered for ``workspace`` source type.

Metric key produced
-------------------
way_count : int
    Subset of ``elements_edited`` where ``type == "way"``.
"""

from __future__ import annotations

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict[str, int | float]:
    """Compute ``way_count``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int | float]
        ``{"way_count": <int>}``
    """
    way_count = sum(1 for e in elements if e["type"] == "way")
    return {"way_count": way_count}
