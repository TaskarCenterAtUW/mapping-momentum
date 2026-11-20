"""
mm.metrics.node_count — count of edited OSM nodes.

Registered for ``workspace`` source type.

Metric key produced
-------------------
node_count : int
    Subset of ``elements_edited`` where ``type == "node"``.

See also ``way_count`` and ``relation_count`` for the other element types.
Together, ``node_count + way_count + relation_count == elements_edited``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mm.metrics.base import register


@register("workspace")
def compute(elements: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Compute ``node_count``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int]
        ``{"node_count": <int>}``
    """
    node_count = sum(1 for e in elements if e["type"] == "node")
    return {"node_count": node_count}
