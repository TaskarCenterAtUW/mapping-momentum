<!-- @format -->

# Mapping Momentum

Statistics engine and report generator for tracking mapping participation metrics in [TDEI Workspaces](https://workspaces.sidewalks.washington.edu/).

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

## Run tests

Pytest configuration lives in [pyproject.toml](pyproject.toml), so there is no separate `pytest.ini` file.

```powershell
python -m pytest tests/unit
python -m ruff check .
```

## Run the CLI

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

Add `--quest-answer-log` to write a `quest-answer-log.csv` beside each activity's `stats.json` and `index.html`:

```powershell
mapping-momentum event --config configs/events/2026-01-20-nda-vancouver `
    --output-dir local-output --quest-answer-log
```

The CSV records each changed quest tag as a row, including its human-readable question and answer, raw tag values, previous answer, submitter, submission time, changeset, OSM element, event, activity, and workspace. It includes choice-based and free-text questions, and records cleared answers with the previous value. Raw tag values are retained in JSON-encoded columns, and formula-like text cells are escaped for safe spreadsheet opening. `--dry-run` suppresses CSV output. When used with `--anonymize`, submitter names and known names in answer text are replaced with participant labels. The flag cannot be combined with `--render-from-stats`, which does not fetch the complete Workspace version history.

Add `--anonymize` (or `-a`) to replace contributor names, map edit-history authors, and quote attributions with labels such as `Participant 1`. The anonymized values are used in both `stats.json` and `index.html`, including `--dry-run` output. Known names are also replaced at whole-word boundaries in note and quote text. When used with `--render-from-stats`, a sanitized copy of `stats.json` and the anonymized HTML are written to the output directory; the input stats file is left unchanged unless it is itself the output file. Review other identifying details in free-form content and images before publication; the option cannot infer names that are not present in structured contributor or quote attribution data.

### Regenerate all configured reports

Run the utility below to discover every event config under `configs/events/`, fetch current Workspace data, and regenerate the full report set:

```powershell
python utilities/generate_all.py
```

The utility skips the template config, writes full event reports and quest-answer logs to `local-output/v<project-version>/full/`, and writes anonymized event reports, logs, and matching aggregates to `local-output/v<project-version>/anonymized/`. It uses configured TDEI credentials or prompts for them. If a live request interrupts a run, pass `--resume` to reuse completed full reports and logs while continuing.

Set `"publish": false` on an event config to exclude that draft from generation, aggregation, publication allowlisting, and the public index. The default is `true`.

### Aggregate reports

Generate each source report first without `--anonymize`, then pass its `stats.json` path (or report directory) to the `aggregate` command. Reports must retain their original usernames so the same person is counted once across events; usernames are matched exactly, including case, and quest-answer counts are summed for each matched username. An anonymized source report is rejected. To anonymize the combined output after matching identities, add `--anonymize` to the aggregate command. The aggregate command verifies that quest-answer totals reconcile with contributor histories. Legacy behavior for missing note authors and legacy per-user totals remains disclosed in the generated report.

```powershell
mapping-momentum aggregate `
    --reports local-output/events/2026-01-20-nda-vancouver/walkabout/stats.json `
              local-output/events/2026-01-29-nda-spanaway/walkabout/stats.json `
    --report-id winter-walk-roll-summary `
    --title "Winter Walk/Roll Contribution Summary" `
    --output-dir local-output
```

The aggregate report is written to `local-output/aggregates/<report-id>/` as `stats.json` and `index.html`. For older `stats.json` files without event labels, the event id is read from the standard `events/<event-id>/<activity-id>/` path.

### Optional: Capture a Workspace fixture

This is for creating an offline test fixture, not a step in report generation. The fixture name must contain only lowercase letters, digits, and hyphens. This command uses the same environment-variable credentials or interactive prompt as the `event` command.

```powershell
mapping-momentum capture --config configs/events/2026-01-20-nda-vancouver `
    --activity-id walkabout --fixture-name 2026-01-20-nda-vancouver-walkabout
```

## Publish to GitHub Pages

Publishing is a manual, two-gate process. Full reports, standalone exports, screenshots, and privacy-check evidence remain local.

1. Generate `local-output/v<project-version>/anonymized/`:

    ```powershell
    python utilities/generate_all.py
    ```

2. Prepare the allowlisted beta commit:

    ```powershell
    mapping-momentum publish prepare
    ```

3. Run the local report checks with the printed full SHA:

    ```powershell
    python -m playwright install chromium
    $env:AXE_CORE_ASSET = "C:\absolute\path\to\axe.min.js"
    mapping-momentum publish check --sha <full-beta-sha>
    ```

    Use a locally pinned `axe.min.js` asset. It is injected only by the local check, never loaded by the published pages.

4. Inspect the report screenshots, collage, visible content, and embedded HTML data. Confirm supplied images were approved for public use. Treat TDEI Workspace IDs as contextual identifiers, not as proof that a private workspace is publicly accessible.

5. Push the exact checked SHA:

    ```powershell
    mapping-momentum publish approve --sha <full-beta-sha>
    ```

    Before the public push, enter this exact affirmation:

    > Yes, I checked these and confirmed there is nothing that needs redaction or anonymization.

The beta push is immediately public and has no separate Pages site. A maintainer dispatches **Promote reviewed Pages snapshot** from `main` with the full reviewed beta SHA. The Pages job verifies that the exact stable commit built successfully and that the served index and Golden Sample match its files.

The Golden Sample is available directly at `golden-sample/index.html` but is not linked from the public index. Automated PII detection, cross-report pseudonym consistency, upstream image redaction, and fully offline exports remain out of scope.

### GitHub Actions setup

Require the `source-quality` check in `main` branch protection. Configure Pages to deploy from the root of `stable`. Create the `pages-promotion` environment, restrict it to `main`, set `PAGES_PUBLIC_URL` to the public site root, and store the designated maintainer's repository-scoped fine-grained PAT with Contents read/write as `MAPPING_MOMENTUM_PUBLISH_PAT`.

For a first publication, GitHub requires the Pages source branch to exist, but the promotion workflow creates `stable`. After the first reviewed beta is ready, dispatch promotion to create `stable`, configure Pages to deploy from its root, then rerun the same dispatch with the same beta SHA; the initial Pages verification may fail before the source is configured, but the stable push is not rolled back and the repeat promotion is idempotent.

Use rollback only to return to a strictly older beta ancestor. If an existing `stable` lacks recognized `Promoted-Beta-SHA` metadata, stop; a maintainer must preserve and verify a legacy backup ref, then deliberately remove the original before rerunning promotion.

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

Reports include a keyboard-accessible Save/Export control that downloads the complete HTML document. Maps and remote media may still require internet access.

Large or dense Workspace areas may return large, truncated, or server-error map responses. The map fetcher accepts map tiles up to 100 MiB, automatically subdivides oversized or truncated responses, and applies bounded subdivision to server errors. Workspace data requests use a 120-second timeout to accommodate large workspaces. If a tile still exceeds the size limit or returns truncated XML at the maximum depth, the command exits with a diagnostic error.

Reports are self-contained with respect to event data, but the interactive map still loads MapLibre from `unpkg.com` and its selectable Positron (the default), Bright, Liberty, Dark, and Fiord basemaps and tiles from `tiles.openfreemap.org` when viewed online. The report can still display its cards when those network resources are unavailable.

Standalone reports use a responsive layout with a Light, Dark, and Auto theme selector. Auto follows the system color preference, and the map switches between Positron and Fiord to match the resolved theme.
