<!-- @format -->

# Mapping Momentum

Statistics engine and report generator for tracking mapping participation metrics.

## Overview

Mapping Momentum generates deterministic per-activity statistics and a self-contained HTML report from a v1.1 event config. The current release is scoped to `workspace` activities.

## Requirements

- Python 3.14
- `uv`
- A virtual environment at `.venv/`
- A TDEI API key in the environment variable that matches the activity environment:
    - `MM_TDEI_API_KEY_PROD`
    - `MM_TDEI_API_KEY_STAGE`
    - `MM_TDEI_API_KEY_DEV`

## Setup

Activate the project virtual environment before running commands:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& .\.venv\Scripts\Activate.ps1
```

Install or refresh the development environment with:

```powershell
uv sync --group dev
```

## Run Tests

Pytest configuration lives in [pyproject.toml](pyproject.toml), so there is no separate `pytest.ini` file.

Run the unit tests with:

```powershell
python -m pytest
```

## Run The CLI

The packaged console script is `mapping-momentum`.

The `event` command reads the committed per-activity quest cache and writes
`stats.json` and `index.html` under the output directory. It does not fetch
quest definitions. Use `capture-quests` to refresh those caches explicitly.

```powershell
$env:MM_TDEI_API_KEY_PROD = 'test-api-key'
mapping-momentum event --config configs/events/nda-vancouver/event.json
```

Capture Workspace responses for an offline fixture (the fixture name must be
lowercase slug text):

```powershell
mapping-momentum capture --config configs/events/nda-vancouver `
    --activity-id walkabout --fixture-name nda-vancouver-walkabout
```

Before a report run, capture the committed quest-definition cache once:

```powershell
mapping-momentum capture-quests --config configs/events/nda-vancouver
```

Generate reports for all activities in the event:

```powershell
mapping-momentum event --config configs/events/nda-vancouver --output-dir local-output
```

Use `--dry-run` to compute and print stats without writing report files. The
normal report path reads the local quest cache and fetches only Workspace map,
changeset, and note data.

Large or dense Workspace areas may return large or truncated map XML. The map
fetcher allows larger map payloads, retries transient malformed responses,
automatically subdivides persistent truncation, and enforces a bounded request
budget. If the API still returns
truncated XML after the limit, the command exits with a diagnostic error;
retrying a smaller event area or using a narrower workspace is preferred to
repeatedly requesting the same large area.

Reports are self-contained with respect to event data, but the interactive map
still loads MapLibre from `unpkg.com` and map styles/tiles from
`tiles.openfreemap.org` when viewed online. The report can still display its
cards when those network resources are unavailable. Do not publish reports
containing participant names, notes, coordinates, or photos without reviewing
their privacy implications.

The committed configurations for Dayton, Everett, Sedro-Woolley, and Spanaway
are event metadata only until their per-activity quest caches are captured.
Dayton also contains placeholder dates and must be completed before use.
