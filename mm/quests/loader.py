"""
mm.quests.loader — load and decode a committed quest-definition.json cache.

The quest definition is a static JSON file committed to the repository by the
``capture-quests`` command.  Report runs read only this cache; they never
contact the network.  This guarantees deterministic output regardless of
upstream quest definition drift.

Quest definition schema (asr-quests v3.x)
------------------------------------------
::

    {
      "version": "3.0.0",
      "elements": [
        {
          "element_type": "Bus Stops",       ← category
          "quests": [
            {
              "quest_id": 101,
              "quest_title": "Is there a ...",  ← question title
              "quest_type": "ExclusiveChoice",
              "quest_tag": "ext:bus_stop_marked_ped_path",  ← OSM tag
              "quest_answer_choices": [
                {"value": "yes", "choice_text": "Yes"},
                ...
              ]
            },
            {
              "quest_type": "TextEntry",
              "quest_tag": "ext:sidewalk_hazards_text",
              ...
              // no quest_answer_choices
            }
          ]
        },
        ...
      ]
    }

The three lookup tables built here drive every downstream consumer
(map markers, quest popup, metric aggregations):

``tag_to_title``
    ``"ext:bus_stop_marked_ped_path"`` → ``"Is there a marked pedestrian path…"``
``tag_value_to_label``
    ``"ext:bus_stop_marked_ped_path"`` → ``{"yes": "Yes", "no": "No", …}``
``tag_to_category``
    ``"ext:bus_stop_marked_ped_path"`` → ``"Bus Stops"``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mm.common.io import read_json


@dataclass
class QuestDefinition:
    """Decoded lookup tables built from a committed quest-definition.json file.

    All three tables are keyed by the ``ext:*`` OSM tag written to elements by
    the Walkabout / asr-quests app.

    Invariants
    ----------
    - Every key in ``tag_value_to_label`` also appears in ``tag_to_title``
      and ``tag_to_category``.
    - Every key in ``tag_to_title`` also appears in ``tag_to_category``
      (and vice versa).
    - TextEntry quests appear in ``tag_to_title`` / ``tag_to_category``
      but are absent from ``tag_value_to_label`` (they have no discrete
      answer choices).
    """

    tag_to_title: dict[str, str]
    """Maps each ext:* quest tag to its quest title (human-readable question)."""

    tag_value_to_label: dict[str, dict[str, str]]
    """Maps each ext:* tag to a {choice_value → display_label} dict.
    TextEntry quests are absent (they accept free-form text, not fixed
    choices)."""

    tag_to_category: dict[str, str]
    """Maps each ext:* quest tag to its element_type / category string
    (e.g. ``"Bus Stops"``, ``"Sidewalks"``, ``"Crossings"``)."""


def load_quest_definition(path: str | Path) -> QuestDefinition:
    """Load a committed ``quest-definition.json`` cache and return a
    ``QuestDefinition`` with decoded lookup tables.

    Parameters
    ----------
    path:
        Path to the ``quest-definition.json`` file (the committed cache for
        one event activity, located at
        ``configs/events/<slug>/quest-definition.json``).

    Returns
    -------
    QuestDefinition
        Populated lookup tables ready for quest decoding.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the JSON lacks the expected top-level ``"elements"`` list.
    json.JSONDecodeError
        If the file is not valid JSON.
    """
    raw: dict[str, Any] = read_json(path)
    return build_lookups(raw)


def build_lookups(raw: dict[str, Any]) -> QuestDefinition:
    """Build lookup tables from a raw quest-definition dict.

    This is the pure, I/O-free core of quest decoding.  It can be called
    with any dict that matches the asr-quests schema — including in-memory
    test fixtures — without touching the filesystem or the network.

    Parameters
    ----------
    raw:
        Parsed content of a ``quest-definition.json`` file.

    Returns
    -------
    QuestDefinition
        Populated lookup tables.

    Raises
    ------
    ValueError
        If ``raw`` lacks the top-level ``"elements"`` list.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("elements"), list):
        raise ValueError("quest definition is missing the top-level 'elements' list")

    tag_to_title: dict[str, str] = {}
    tag_value_to_label: dict[str, dict[str, str]] = {}
    tag_to_category: dict[str, str] = {}

    for element_index, element in enumerate(raw["elements"]):
        if not isinstance(element, dict):
            raise ValueError(f"elements[{element_index}] must be an object")
        category: str = element.get("element_type", "")
        if not isinstance(category, str):
            raise ValueError(f"elements[{element_index}].element_type must be a string")
        quests = element.get("quests", [])
        if not isinstance(quests, list):
            raise ValueError(f"elements[{element_index}].quests must be a list")
        for quest_index, quest in enumerate(quests):
            if not isinstance(quest, dict):
                raise ValueError(
                    f"elements[{element_index}].quests[{quest_index}] must be an object"
                )
            tag: str = quest.get("quest_tag", "")
            if not tag:
                continue
            if not isinstance(tag, str):
                raise ValueError(
                    f"elements[{element_index}].quests[{quest_index}].quest_tag "
                    "must be a string"
                )
            title = quest.get("quest_title", "")
            if not isinstance(title, str):
                raise ValueError(
                    f"elements[{element_index}].quests[{quest_index}].quest_title "
                    "must be a string"
                )

            # Some upstream definitions reuse generic OSM keys such as
            # ``surface`` for different element types. Preserve each
            # category's first definition while retaining a deterministic
            # global lookup for decoding the shared tag.
            is_first_definition = tag not in tag_to_title
            if is_first_definition:
                tag_to_title[tag] = title
                tag_to_category[tag] = category

            choices = quest.get("quest_answer_choices")
            if choices is None:
                continue
            if not isinstance(choices, list):
                raise ValueError(
                    f"elements[{element_index}].quests[{quest_index}]."
                    "quest_answer_choices must be a list"
                )
            labels: dict[str, str] = {}
            for choice_index, choice in enumerate(choices):
                if not isinstance(choice, dict) or not isinstance(
                    choice.get("value"), str
                ):
                    raise ValueError(
                        f"elements[{element_index}].quests[{quest_index}]."
                        f"quest_answer_choices[{choice_index}] must contain a "
                        "string value"
                    )
                value = choice["value"]
                label = choice.get("choice_text", value)
                if not isinstance(label, str):
                    raise ValueError(
                        f"elements[{element_index}].quests[{quest_index}]."
                        f"quest_answer_choices[{choice_index}].choice_text must "
                        "be a string"
                    )
                if value in labels:
                    raise ValueError(
                        f"duplicate answer value for quest {tag!r}: {value!r}"
                    )
                labels[value] = label
            if labels and is_first_definition:
                tag_value_to_label[tag] = labels

    return QuestDefinition(
        tag_to_title=tag_to_title,
        tag_value_to_label=tag_value_to_label,
        tag_to_category=tag_to_category,
    )
