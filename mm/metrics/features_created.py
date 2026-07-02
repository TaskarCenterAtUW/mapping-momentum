"""
mm.metrics.features_created — features-created-during-event metric.

Registered for ``workspace`` source type.

Metric key produced
-------------------
features_created : list[dict]
    One entry per OSM element type (``node``, ``way``, ``relation``)
    for elements whose first changeset action was ``"create"`` within
    the event window.  Entries are sorted by ``count`` descending.

    Each entry::

        {
            "feature_type": str,   # OSM element type: "node", "way", or "relation"
            "count":        int,   # number of elements of this type that were created
        }
"""

from __future__ import annotations

from collections import Counter

from mm.metrics.base import register


@register("workspace")
def compute(elements: list[dict]) -> dict:
    """Compute ``features_created``.

    Parameters
    ----------
    elements:
        Enriched element dicts as produced by the workspace pipeline.
        Uses ``kind`` and ``type`` on each element.

    Returns
    -------
    dict
        ``{"features_created": [{"feature_type": str, "count": int}, …]}``
    """
    counts: Counter[str] = Counter()

    for elem in elements:
        if elem.get("kind") == "create":
            feature_type: str = elem.get("type", "unknown")
            counts[feature_type] += 1

    created = [
        {"feature_type": ft, "count": count} for ft, count in counts.most_common()
    ]
    return {"features_created": created}
