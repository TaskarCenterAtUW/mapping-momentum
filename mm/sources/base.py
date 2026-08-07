"""
mm.sources.base — shared types for source adapters.

``Element`` is the normalized in-memory representation of a single OSM
element (node, way, or relation) as produced by any source adapter.
``Version`` is a typed record of one changeset snapshot of an element.
``SourceResult`` bundles the filtered element list with pipeline metadata
so metric modules receive a self-contained, typed package and never need
to know where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

# ---------------------------------------------------------------------------
# Version — one changeset snapshot of an OSM element
# ---------------------------------------------------------------------------


class Version(TypedDict):
    """A single versioned snapshot of an OSM element from a changeset.

    Instances are collected in ``Element["versions"]``, ordered oldest-first
    (ascending by ``timestamp``).

    Fields
    ------
    action:
        The OsmChange action that produced this version:
        ``"create"``, ``"modify"``, or ``"delete"``.
    user:
        OSM username of the editor.
    timestamp:
        ISO 8601 UTC string of when this version was saved.
    changeset:
        OSM changeset ID.
    tags:
        Raw OSM tags at this version (empty dict for a delete entry).
    readable:
        Decoded quest diffs between the previous version and this one:
        ``{tag_key: {"old": str | None, "new": str | None}}``.
        Only quest-tagged keys with a changed value are included.
        Empty dict when no quest definition is available.
    photos:
        KartaView field-photo URLs captured in this version (extracted
        from ``PHOTO_TAG_KEY`` on the element's tags at this version).
    """

    action: str
    user: str
    timestamp: str
    changeset: int
    tags: dict[str, str]
    readable: dict[str, Any]
    photos: list[str]


# ---------------------------------------------------------------------------
# Element — normalized OSM element dict
# ---------------------------------------------------------------------------

# Keys present on ALL element types:
#
#   type        str              "node" | "way" | "relation"
#   id          int              OSM element ID
#   timestamp   str              ISO 8601 UTC string of the last edit
#   user        str              OSM username of the last editor
#   uid         int              OSM numeric user ID of the last editor
#   changeset   int              OSM changeset ID of the last edit
#   tags        dict[str, str]   key/value OSM tags (empty dict if none)
#
# Additional keys on nodes:
#   lat         float            WGS84 latitude
#   lon         float            WGS84 longitude
#
# Additional keys on ways:
#   nodes       list[int]        ordered list of member node ref IDs
#
# Enriched keys added by the pipeline (Slice C+):
#
#   kind        str              "quest" | "create" | "note"
#   category    str              element_type from the quest definition
#                                (e.g. "Sidewalks", "Crossings"); "" if unknown
#   versions    list[Version]    version history from changesets, oldest-first;
#                                empty list until changeset data is processed
#   photos      list[str]        KartaView field-photo URLs (from PHOTO_TAG_KEY)
#   readable    dict[str, str]   decoded current quest tags: {tag: label}
#   geom        list | None      [[lat, lon], …] polyline for ways; None otherwise
#   text        str              note body text (note elements only)
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
