"""
mm.quests.capture — fetch and cache a remote quest-definition.json.

This module is called exclusively by the ``capture-quests`` CLI subcommand.
Report runs must never import or call anything from this module; they read
only the committed cache produced here.

Two functions are provided:

``capture_quest_definition(url, dest)``
    Fetch the upstream quest definition, validate it as JSON, write it to
    *dest*, and return the UTC retrieval timestamp.

``stamp_retrieval_date(event_json_path, activity_id, retrieval_date)``
    Update a specific activity in ``event.json`` with the retrieval
    timestamp so callers can track cache freshness without a network round-trip.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mm.common.http import fetch_bytes
from mm.common.io import read_json, write_json


def capture_quest_definition(url: str, dest: Path) -> str:
    """Fetch the quest definition at *url* and write it to *dest*.

    The response body is validated as JSON before being written.  The
    file is written with ``write_json`` (2-space indent, UTF-8) so the
    committed cache produces stable diffs.

    Parameters
    ----------
    url:
        Raw URL of the upstream quest definition (the value of
        ``quest_definition_url`` in the event activity config).
    dest:
        Destination file path.  Parent directories are created if absent.
        Typically ``configs/events/<slug>/quest-definition.json``.

    Returns
    -------
    str
        UTC ISO 8601 retrieval timestamp, e.g. ``"2026-06-26T14:32:00Z"``.
        Callers should pass this to ``stamp_retrieval_date``.

    Raises
    ------
    mm.common.http.HTTPError
        If the upstream URL returns a non-2xx response or the connection
        fails.
    json.JSONDecodeError
        If the response body is not valid JSON.
    """
    raw_bytes = fetch_bytes(url)
    # Validate JSON before writing — raises json.JSONDecodeError on bad input.
    definition = json.loads(raw_bytes)

    retrieval_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    write_json(dest, definition)

    return retrieval_date


def stamp_retrieval_date(
    event_json_path: Path,
    activity_id: str,
    retrieval_date: str,
) -> None:
    """Stamp *retrieval_date* onto the matching activity in *event_json_path*.

    Reads the event JSON, finds the activity whose ``id`` is *activity_id*,
    sets ``quest_definition_retrieval_date``, and writes the file back in
    place.

    Parameters
    ----------
    event_json_path:
        Path to the ``event.json`` file to update.
    activity_id:
        The ``id`` of the workspace activity to update.
    retrieval_date:
        UTC ISO 8601 timestamp string (e.g. ``"2026-06-26T14:32:00Z"``).

    Raises
    ------
    KeyError
        If no activity with *activity_id* exists in the event config.
    """
    config = read_json(event_json_path)
    for activity in config.get("activities", []):
        if activity.get("id") == activity_id:
            activity["quest_definition_retrieval_date"] = retrieval_date
            write_json(event_json_path, config)
            return
    raise KeyError(f"no activity with id {activity_id!r} found in {event_json_path}")
