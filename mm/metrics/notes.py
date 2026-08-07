"""
mm.metrics.notes — note count metric.

Registered for ``workspace`` source type.

Metric key produced
-------------------
note_count : int
    Number of elements with ``kind == "note"`` in the filtered set.
    These are field notes added by mappers via the app, distinct from
    edits to OSM map features.
"""

from __future__ import annotations

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict:
    """Compute ``note_count``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Note elements have ``kind == "note"``.

    Returns
    -------
    dict
        ``{"note_count": <int>}``
    """
    note_count = sum(1 for e in elements if e.get("kind") == "note")
    return {"note_count": note_count}
