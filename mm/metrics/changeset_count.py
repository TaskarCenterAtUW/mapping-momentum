"""
mm.metrics.changeset_count — count of unique OSM changesets.

Registered for ``workspace`` source type.

Metric key produced
-------------------
changeset_count : int
    Number of distinct OSM changeset IDs across all elements in the
    filtered set. Enriched elements use their event-window version
    histories; elements without histories use their top-level
    ``changeset`` field.
"""

from __future__ import annotations

from typing import Any, TypeGuard

from mm.metrics.base import register


def _is_json_array(value: Any) -> TypeGuard[list[Any]]:
    """Return whether *value* is a JSON array."""
    return isinstance(value, list)


def _is_json_object(value: Any) -> TypeGuard[dict[str, Any]]:
    """Return whether *value* is a JSON object."""
    return isinstance(value, dict)


@register("workspace")
def compute(elements: list[dict[str, Any]]) -> dict[str, int | float]:
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
    changesets: set[int | str] = set()
    for element in elements:
        if element.get("kind") == "note":
            continue

        versions = element.get("versions")
        if _is_json_array(versions) and versions:
            for version in versions:
                if not _is_json_object(version):
                    continue
                changeset = version.get("changeset")
                if isinstance(changeset, (int, str)) and not isinstance(
                    changeset, bool
                ):
                    changesets.add(changeset)
            continue

        changeset = element.get("changeset")
        if isinstance(changeset, (int, str)) and not isinstance(changeset, bool):
            changesets.add(changeset)

    return {"changeset_count": len(changesets)}
