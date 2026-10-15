<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/) and
[Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased] - 2026-10-09

### Added

- Added report support for local picture files/directories, quote lists with
  optional attribution, slideshow image URLs, and hosted or direct video URLs.
- Embedded local report pictures into generated stats and rendered the new
  content sections in HTML reports.
- Added complete synthetic minimal and maximal offline runs under `example/`,
  including raw Workspace payloads, quest caches, SVG assets, and an end-to-end
  runner.
- Included generated `stats.json` and `index.html` artifacts for both offline
  examples, with links and regeneration commands in `example/README.md`.

### Fixed

- Corrected Python exception tuple syntax in Workspace parsing and time
  filtering so the full test suite runs on Python 3.

## [1.0.0] - 2026-08-07

### Added

- Initial release

## [0.1.0] - 2026-04-22

### Added

- Initial commit

[0.2.0]: https://github.com/taskarcenteratuw/mapping-momentum/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/taskarcenteratuw/mapping-momentum/releases/tag/v0.1.0
