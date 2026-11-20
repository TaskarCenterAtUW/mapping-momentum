---
name: iterative-report-development
description: Use when iterating on Mapping Momentum event or aggregate report content, templates, styles, or interactions; render selected reports from existing stats instead of regenerating the full suite.
---

<!-- @format -->

# Iterative Report Development

Use this workflow to make and preview focused Mapping Momentum report changes without rerunning every configured event.

## Guardrails

- Inspect the relevant template, rendering tests, and event config before changing anything; keep the change limited to the requested report behavior.
- Classify the change: template, CSS, and client-side interaction edits can be previewed from existing stats; metric or source-data changes require fresh stats for only the affected event(s).
- Never use `utilities/generate_all.py` for an interactive iteration, including `--resume`; it still regenerates anonymized reports and aggregates across the configured suite.
- Keep generated files under the ignored `local-output/v<project-version>/` tree and do not prepare, push, or promote a publication snapshot during design iteration.
- Treat full stats and reports as identifying data; preview anonymized output by default, but follow explicit requests to inspect full local reports without pasting participant details into chat.
- When updating `CHANGELOG.md`, keep entries concise and outcome-focused; omit extra implementation details.
- Run terminal commands only after activating the project environment with `.\.venv\Scripts\Activate.ps1`.

## Current SRTS Scope

The current SRTS event configs are `2026-10-18-srts-john-stanford-intl`, `2026-11-01-srts-john-stanford-intl`, and `2026-11-15-srts-cleveland`; each currently has one `walkabout` activity, and all three belong to the `srts` aggregate series.

Full source stats are expected at `local-output/v<project-version>/full/events/<event-id>/walkabout/stats.json`; anonymized event reports are written under `local-output/v<project-version>/anonymized/events/<event-id>/walkabout/`.

## Bootstrap Missing Stats Only

Check whether each selected event already has full `stats.json`. If one is missing and the task requires a data refresh, ask before fetching authenticated Workspace data unless the user has explicitly requested that fetch; run only that event, never the full suite.

```powershell
.\.venv\Scripts\Activate.ps1
$Version = python -c "import tomllib; from pathlib import Path; print(tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
$FullRoot = "local-output\v$Version\full"
$SrtsEvents = @(
    "2026-10-18-srts-john-stanford-intl",
    "2026-11-01-srts-john-stanford-intl",
    "2026-11-15-srts-cleveland"
)
foreach ($EventId in $SrtsEvents) {
    $StatsPath = "$FullRoot\events\$EventId\walkabout\stats.json"
    if (-not (Test-Path $StatsPath)) {
        mapping-momentum event --config "configs\events\$EventId\event.json" --output-dir $FullRoot --quest-answer-log
        if ($LASTEXITCODE -ne 0) { throw "Event generation failed for $EventId" }
    }
}
```

## Re-render Events and Aggregate

Run this block after each report-template edit; `--render-from-stats` avoids live requests, and aggregation must use original full stats so contributor identities can be reconciled before anonymization.

```powershell
.\.venv\Scripts\Activate.ps1
$Version = python -c "import tomllib; from pathlib import Path; print(tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
$FullRoot = "local-output\v$Version\full"
$AnonymizedRoot = "local-output\v$Version\anonymized"
$SrtsEvents = @(
    "2026-10-18-srts-john-stanford-intl",
    "2026-11-01-srts-john-stanford-intl",
    "2026-11-15-srts-cleveland"
)
$StatsPaths = foreach ($EventId in $SrtsEvents) {
    "$FullRoot\events\$EventId\walkabout\stats.json"
}
foreach ($EventId in $SrtsEvents) {
    $Config = "configs\events\$EventId\event.json"
    $StatsPath = "$FullRoot\events\$EventId\walkabout\stats.json"
    if (-not (Test-Path $StatsPath)) { throw "Missing full stats: $StatsPath" }
    mapping-momentum event --config $Config --render-from-stats $StatsPath --output-dir $FullRoot
    if ($LASTEXITCODE -ne 0) { throw "Full report render failed for $EventId" }
    mapping-momentum event --config $Config --render-from-stats $StatsPath --output-dir $AnonymizedRoot --anonymize
    if ($LASTEXITCODE -ne 0) { throw "Anonymized report render failed for $EventId" }
}
mapping-momentum aggregate --reports $StatsPaths --report-id srts --title "SRTS Aggregate Contribution Report" --output-dir "$FullRoot\events"
if ($LASTEXITCODE -ne 0) { throw "Full SRTS aggregate failed" }
mapping-momentum aggregate --reports $StatsPaths --report-id srts --title "SRTS Aggregate Contribution Report" --output-dir "$AnonymizedRoot\events" --anonymize
if ($LASTEXITCODE -ne 0) { throw "Anonymized SRTS aggregate failed" }
```

The resulting anonymized previews are `local-output/v<project-version>/anonymized/events/<event-id>/walkabout/index.html` and `local-output/v<project-version>/anonymized/events/aggregates/srts/index.html`.

## Inspect and Verify

- Open the anonymized event reports and aggregate in a browser; reuse the same preview tab after rerendering, and check desktop/mobile layouts, theme states, keyboard behavior, and export behavior when those areas changed.
- If the user shares an active browser page, reuse and reload that tab after rendering; when matching control size, compare rendered bounds in the browser rather than relying on class names or CSS declarations alone.
- Run the focused regression tests `python -m pytest tests/unit/test_outputs.py tests/unit/test_aggregate.py`; add or adjust focused assertions for any new behavior.
- In the final summary, include **Updated test contracts:** followed by one bullet for every added or updated test, formatted as `- <test_function_name>: <plain-language contract describing the protected behavior and expected outcome>.`
- For changes to metric or aggregation logic, regenerate only the affected source event stats with the normal `event` command, then rebuild the `srts` aggregate from all three full stats files.
- Summarize which reports were rerendered, the exact output paths, and any tests or visual checks performed; leave publication checks for an explicitly requested release-candidate review.
