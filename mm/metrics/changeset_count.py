"""
mm.metrics.changeset_count — count of unique OSM changesets.

Registered for ``workspace`` source type.

Metric key produced
-------------------
changeset_count : int
    Number of distinct OSM changeset IDs (``changeset`` field) across
    all elements in the filtered set.  A changeset that straddles the
    event boundary is counted if any of its elements appear in the
    filtered set — so this is a proxy for "changesets active during the
    event", not a strict count of changesets opened and closed within
    the window.
"""

from __future__ import annotations

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict[str, int | float]:
    """Compute ``changeset_count``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int | float]
        ``{"changeset_count": <int>}``
    """
    changeset_count = len({e["changeset"] for e in elements})
    return {"changeset_count": changeset_count}
