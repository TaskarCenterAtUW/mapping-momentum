<!-- @format -->

# Mapping Momentum

Statistics engine and report generator for tracking mapping participation metrics.

## Overview

Mapping Momentum generates deterministic per-activity statistics and self-contained HTML reports from event configs. It can also combine existing reports into an aggregate contribution summary.

## Requirements

- Python 3.14
- `uv`
- A virtual environment at `.venv/`
- A TDEI account with access to the target workspace. Live commands require an interactive terminal unless credentials are supplied through environment variables.

For live Workspace requests, the `event` and `capture` commands use a short-lived access token. By default, they prompt for the TDEI username and password, with the password hidden. For programmatic runs, set both environment variables for each activity environment:

| Activity environment | Username variable        | Password variable        |
| -------------------- | ------------------------ | ------------------------ |
| `prod`               | `MM_TDEI_USERNAME_PROD`  | `MM_TDEI_PASSWORD_PROD`  |
| `stage`              | `MM_TDEI_USERNAME_STAGE` | `MM_TDEI_PASSWORD_STAGE` |
| `dev`                | `MM_TDEI_USERNAME_DEV`   | `MM_TDEI_PASSWORD_DEV`   |

Set both variables for an environment or neither; partial pairs and empty values are errors. If neither is set, interactive authentication remains available. The CLI does not print or persist credential values; it sends them to the TDEI authentication endpoint and retains only the resulting token in memory. Inject credentials from a CI or OS secret store, limit their lifetime, and avoid putting values in source files, command-line arguments, or logs. Environment variables may be visible to other processes running as the same user.

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
    mapping-momentum capture-quests --config configs/events/2026-01-20-nda-vancouver
    ```

2. Generate the report for every activity in the event. The command reads the local quest cache and fetches live Workspace map, changeset, and note data. It prompts for credentials unless the matching environment-variable pair is set. Reports are written under `local-output/events/<event-id>/<activity-id>/` as `stats.json` and `index.html`.

    ```powershell
    mapping-momentum event --config configs/events/2026-01-20-nda-vancouver/event.json `
        --output-dir local-output
    ```

Use `--dry-run` with the `event` command to print stats without writing report files.

Add `--anonymize` (or `-a`) to replace contributor names, map edit-history authors, and quote attributions with labels such as `Participant 1`. The anonymized values are used in both `stats.json` and `index.html`, including `--dry-run` output. Known names are also replaced at whole-word boundaries in note and quote text. When used with `--render-from-stats`, a sanitized copy of `stats.json` and the anonymized HTML are written to the output directory; the input stats file is left unchanged unless it is itself the output file. Review other identifying details in free-form content and images before publication; the option cannot infer names that are not present in structured contributor or quote attribution data.

### Aggregate reports

Generate each source report first without `--anonymize`, then pass its `stats.json` path (or report directory) to the `aggregate` command. Reports must retain their original usernames so the same person is counted once across events; usernames are matched exactly, including case, and quest-answer counts are summed for each matched username. An anonymized source report is rejected. To anonymize the combined output after the identities have been matched, add `--anonymize` to the aggregate command. The aggregate command checks that quest-answer totals reconcile with contributor histories. For legacy reports without per-user totals, complete marker histories can supply the contributor counts; if those counts exceed a legacy report's stored changeset total, the aggregate uses the history total and discloses the difference. It rejects legacy histories that fall short and current reports with inconsistent totals. Legacy reports without note authors retain their overall note totals, with those notes marked as unattributed rather than assigned to a contributor.

```powershell
mapping-momentum event --config configs/events/2026-01-20-nda-vancouver `
    --output-dir local-output

mapping-momentum event --config configs/events/2026-01-29-nda-spanaway `
    --output-dir local-output

mapping-momentum aggregate `
    --reports local-output/events/2026-01-20-nda-vancouver/walkabout/stats.json `
              local-output/events/2026-01-29-nda-spanaway/walkabout/stats.json `
    --report-id winter-walk-roll-summary `
    --title "Winter Walk/Roll Contribution Summary" `
    --output-dir local-output
```

The aggregate report is written to `local-output/aggregates/<report-id>/` as `stats.json` and `index.html`. Use `--reports` with any number of generated report paths. For older `stats.json` files without event labels, the output uses the event id from the standard `events/<event-id>/<activity-id>/` path.

### Optional: Capture a Workspace fixture

This is for creating an offline test fixture, not a step in report generation. The fixture name must contain only lowercase letters, digits, and hyphens. This command uses the same environment-variable credentials or interactive prompt as the `event` command.

```powershell
mapping-momentum capture --config configs/events/2026-01-20-nda-vancouver `
    --activity-id walkabout --fixture-name 2026-01-20-nda-vancouver-walkabout
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

Reports are self-contained with respect to event data, but the interactive map still loads MapLibre from `unpkg.com` and its selectable Positron (the default), Bright, Liberty, Dark, and Fiord basemaps and tiles from `tiles.openfreemap.org` when viewed online. The report can still display its cards when those network resources are unavailable.
