"""
mm.sources.base — shared types for source adapters.

``Element`` is the normalized in-memory representation of a single OSM
element (node, way, or relation) as produced by any source adapter.
``SourceResult`` bundles the filtered element list with pipeline metadata
so metric modules receive a self-contained, typed package and never need
to know where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Normalized OSM element dict.  Keys present on all element types:
#
#   type        str             "node" | "way" | "relation"
#   id          int             OSM element ID
#   timestamp   str             ISO 8601 UTC string, e.g. "2026-01-20T19:00:00Z"
#   user        str             OSM username
#   uid         int             OSM numeric user ID
#   changeset   int             OSM changeset ID
#   tags        dict[str, str]  key/value OSM tags (empty dict if none)
#
# Additional keys present only on nodes:
#   lat         float           WGS84 latitude
#   lon         float           WGS84 longitude
#
# Additional keys present only on ways:
#   nodes       list[int]       ordered list of member node ref IDs
Element = dict[str, Any]


@dataclass
class SourceResult:
    """The output of one source adapter run.

    Attributes
    ----------
    source_type:
        Identifies the adapter that produced this result
        (``"workspace"`` in v1).
    activity_id:
        The ``id`` of the activity config entry this result corresponds
        to.  Used for output-path construction downstream.
    window_start:
        Inclusive start of the event time window (timezone-aware UTC
        ``datetime``).
    window_end:
        Exclusive end of the event time window (timezone-aware UTC
        ``datetime``).
    elements:
        Normalized OSM elements that fall within ``[window_start,
        window_end)``.
    """

    source_type: str
    activity_id: str
    window_start: datetime
    window_end: datetime
    elements: list[Element] = field(default_factory=list)
