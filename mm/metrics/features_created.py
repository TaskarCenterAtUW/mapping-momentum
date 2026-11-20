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
from collections.abc import Mapping, Sequence
from typing import TypedDict

from mm.metrics.base import register


class CreatedFeatureCount(TypedDict):
    """Count of created features for an element type."""

    feature_type: str
    count: int


@register("workspace")
def compute(
    elements: Sequence[Mapping[str, object]],
) -> dict[str, list[CreatedFeatureCount]]:
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
            feature_type = elem.get("type", "unknown")
            if not isinstance(feature_type, str):
                raise TypeError("created element type must be a string")
            counts[feature_type] += 1

    created: list[CreatedFeatureCount] = [
        {"feature_type": ft, "count": count}
        for ft, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"features_created": created}
