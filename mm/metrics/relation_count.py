"""
mm.metrics.relation_count — count of edited OSM relations.

Registered for ``workspace`` source type.

Metric key produced
-------------------
relation_count : int
    Subset of ``elements_edited`` where ``type == "relation"``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mm.metrics.base import register


@register("workspace")
def compute(elements: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Compute ``relation_count``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int]
        ``{"relation_count": <int>}``
    """
    relation_count = sum(1 for e in elements if e["type"] == "relation")
    return {"relation_count": relation_count}
