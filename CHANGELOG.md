<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/) and [Conventional Commits](https://www.conventionalcommits.org/).

## [v1.5.0] - 2026-11-15

### Added

- Added interactive map-element details with per-version tag diffs and contributor and changeset metadata.
- Added a generic link from the photo gallery to open the full-size image in a new tab.
- Regenerated anonymized output reports with new features implemented.

### Fixed

- Kept interactive map icons aligned with the basemap during pan and zoom by rendering them in MapLibre layers.
- Centered the photo gallery popup in the viewport.
- Made the photo gallery dismissible with Escape.
- Fixed contributor and tag-diff map popups closing immediately after marker clicks.

## [v1.4.0] - 2026-11-04

### Added

- Added opt-in `event --quest-answer-log` CSV export with per-answer question, answer, submitter, timestamp, changeset, and feature metadata.

## [v1.3.0] - 2026-10-26

### Added

- Added `--anonymize` (`-a`) parameter to replace structured participant names with stable `Participant N` labels in report data, map histories, and quote attributions.
- Added anonymized minimal and maximal offline sample reports.
- Added optional environment-variable credentials for programmatic TDEI authentication while retaining secure interactive prompts.
- Added a viewer basemap selector for OpenFreeMap's Positron (default), Bright, Liberty, Dark, and Fiord styles.
- Added a persistent, accessible light/dark theme toggle to HTML reports, with TCAT Wiki purple/gold accents and automatic Fiord basemaps in dark mode.
- Added an `aggregate` command to merge non-anonymized per-event reports, deduplicate contributors by username, and produce a cross-event HTML summary.
- Added anonymized outputs and aggregates for all existing event configs.

### Changed

- Applied standardized formatting and updated event configs.

## [v1.2.0] - 2026-10-19

### Changed

- Updated Workspace authentication to use interactive TDEI login prompts and send the short-lived access token using the workspace-ID Basic auth format. The CLI no longer requires persistent credential environment variables.
- Increased the Workspace API data-request timeout to 120 seconds for large workspaces and added endpoint context to timeout errors.
- Automatically subdivided oversized map responses into smaller Workspace requests instead of failing at the per-response byte limit.

## [v1.1.1] - 2026-10-19

### Added

- Added report support for local picture files/directories, quote lists with optional attribution, slideshow image URLs, and hosted or direct video URLs.
- Embedded local report pictures into generated stats and rendered the new content sections in HTML reports.
- Added complete synthetic minimal and maximal offline runs under `example/`, including raw Workspace payloads, quest caches, SVG assets, and an end-to-end runner.
- Included generated `stats.json` and `index.html` artifacts for both offline examples, with links and regeneration commands in `example/README.md`.

### Fixed

- Corrected Python exception tuple syntax in Workspace parsing and time filtering so the full test suite runs on Python 3.
- Made nested `report` media settings override event-level settings and scoped offline example credentials to config validation.
- Fixed changelog content and formatting.

## [v1.0.0] - 2026-08-07

### Added

- Initial release

## [v0.1.0] - 2026-04-22

### Added

- Initial commit
