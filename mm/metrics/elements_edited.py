"""
mm.metrics.elements_edited — count of all edited elements.

Registered for ``workspace`` source type.

Metric key produced
-------------------
elements_edited : int
    Total count of OSM elements (nodes, ways, and relations) in the
    filtered set.  Reflects the number of distinct elements touched
    during the event.

Note: The Workspace ``/map`` endpoint returns the *current* state of
all elements — it does not include deleted elements.  ``elements_edited``
therefore counts elements whose most recent visible version was
created or last modified within the event time window.
"""

from __future__ import annotations

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict[str, int | float]:
    """Compute ``elements_edited``.

    Parameters
    ----------
    elements:
        Normalized OSM element dicts as produced by a source adapter
        and filtered to the event time window.

    Returns
    -------
    dict[str, int | float]
        ``{"elements_edited": <int>}``
    """
    elements_edited = len(elements)
    return {"elements_edited": elements_edited}
