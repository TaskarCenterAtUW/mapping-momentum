<!-- @format -->

# Mapping Momentum

Statistics engine and report generator for tracking mapping participation metrics.

## Overview

Mapping Momentum generates deterministic per-activity statistics and a self-contained HTML report from a v1.1 event config. The current release is scoped to `workspace` activities.

## Requirements

- Python 3.14
- `uv`
- A virtual environment at `.venv/`
- An interactive terminal and a TDEI account with access to the target workspace.

For live Workspace requests, the `event` and `capture` commands prompt for the TDEI username and password. The password is hidden while entered. The CLI exchanges the credentials for a short-lived access token and does not write the credentials to disk or environment variables.

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

Run these commands from the repository root after completing Setup. The packaged console script is `mapping-momentum`.

1. Ensure the event's quest definitions are cached. Run this when the cache is missing or you want to refresh it; it fetches each definition and updates the event config's retrieval timestamp. Skip this step if the committed cache is already present and current.

    ```powershell
    mapping-momentum capture-quests --config configs/events/nda-vancouver
    ```

2. Generate the report for every activity in the event. The command reads the local quest cache, fetches live Workspace map, changeset, and note data, then prompts for your TDEI username and hidden password. The credentials aren't saved. Reports are written under `local-output/events/<event-id>/<activity-id>/` as `stats.json` and `index.html`.

    ```powershell
    mapping-momentum event --config configs/events/nda-vancouver/event.json `
        --output-dir local-output
    ```

Use `--dry-run` with the `event` command to print stats without writing report files.

### Optional: Capture a Workspace fixture

This is for creating an offline test fixture, not a step in report generation.
The fixture name must contain only lowercase letters, digits, and hyphens.
This command also prompts for TDEI credentials.

```powershell
mapping-momentum capture --config configs/events/nda-vancouver `
    --activity-id walkabout --fixture-name nda-vancouver-walkabout
```

## Report content

Optional event content can be configured at the event level or inside the `report` object:

```json
{
    "pictures": ["pictures/volunteers.jpg"],
    "quotes": [
        {
            "quote": "Everyone can contribute.",
            "first_name": "Alex",
            "last_name": "Mapper",
            "organization": "TDEI",
            "title": "Participant"
        }
    ],
    "slideshow_url": ["https://example.com/event/001.jpg"],
    "video_url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```

`pictures` accepts a list of relative image paths or a relative directory. Local files are embedded in the report. `slideshow_url` accepts one slideshow or image-directory URL, or a list of individual image URLs. `video_url` accepts a hosted video URL (YouTube and Vimeo links are embedded) or a direct video-file URL. Quote attribution fields are optional.

Large or dense Workspace areas may return large or truncated map XML. The map fetcher accepts map tiles up to 100 MiB, automatically subdivides oversized or truncated responses, and enforces bounded tile-depth and request limits. Workspace data requests use a 120-second timeout to accommodate large workspaces. If a tile still exceeds the size limit or returns truncated XML at the maximum depth, the command exits with a diagnostic error.

Reports are self-contained with respect to event data, but the interactive map still loads MapLibre from `unpkg.com` and map styles/tiles from `tiles.openfreemap.org` when viewed online. The report can still display its cards when those network resources are unavailable.
