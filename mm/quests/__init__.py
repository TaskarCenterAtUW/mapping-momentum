"""
mm.quests — quest definition loading, caching, and decoding.

Public API
----------
``load_quest_definition(path)``
    Load a committed ``quest-definition.json`` cache and return a
    ``QuestDefinition`` with decoded lookup tables.

``build_lookups(raw)``
    Pure function: build lookup tables from a raw quest-definition dict.

``capture_quest_definition(url, dest)``
    Fetch the upstream quest definition and write it to *dest*.
    Only called by the ``capture-quests`` CLI subcommand.

``stamp_retrieval_date(event_json_path, activity_id, retrieval_date)``
    Update an activity in ``event.json`` with the retrieval timestamp.
    Only called by the ``capture-quests`` CLI subcommand.
"""

from mm.quests.capture import capture_quest_definition, stamp_retrieval_date
from mm.quests.loader import QuestDefinition, build_lookups, load_quest_definition

__all__ = [
    "QuestDefinition",
    "build_lookups",
    "load_quest_definition",
    "capture_quest_definition",
    "stamp_retrieval_date",
]
