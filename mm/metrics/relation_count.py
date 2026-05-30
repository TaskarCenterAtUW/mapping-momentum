"""
mm.metrics.relation_count — count of edited OSM relations.

Registered for ``workspace`` source type.

Metric key produced
-------------------
relation_count : int
    Subset of ``elements_edited`` where ``type == "relation"``.
"""

from __future__ import annotations

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict[str, int | float]:
    """Compute ``relation_count``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int | float]
        ``{"relation_count": <int>}``
    """
    relation_count = sum(1 for e in elements if e["type"] == "relation")
    return {"relation_count": relation_count}
