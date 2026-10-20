<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/) and [Conventional Commits](https://www.conventionalcommits.org/).

## [1.2.0] - 2026-10-19

### Changed

- Updated Workspace authentication to use interactive TDEI login prompts and send the short-lived access token using the workspace-ID Basic auth format. The CLI no longer requires persistent credential environment variables.
- Increased the Workspace API data-request timeout to 120 seconds for large workspaces and added endpoint context to timeout errors.
- Automatically subdivided oversized map responses into smaller Workspace requests instead of failing at the per-response byte limit.

## [1.1.1] - 2026-10-19

### Added

- Added report support for local picture files/directories, quote lists with optional attribution, slideshow image URLs, and hosted or direct video URLs.
- Embedded local report pictures into generated stats and rendered the new content sections in HTML reports.
- Added complete synthetic minimal and maximal offline runs under `example/`, including raw Workspace payloads, quest caches, SVG assets, and an end-to-end runner.
- Included generated `stats.json` and `index.html` artifacts for both offline examples, with links and regeneration commands in `example/README.md`.

### Fixed

- Corrected Python exception tuple syntax in Workspace parsing and time filtering so the full test suite runs on Python 3.
- Made nested `report` media settings override event-level settings and scoped offline example credentials to config validation.
- Fixed changelog content and formatting.

## [1.0.0] - 2026-08-07

### Added

- Initial release

## [0.1.0] - 2026-04-22

### Added

- Initial commit
