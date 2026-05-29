<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/) and
[Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

## [0.2.0] - 2026-05-29

### Added

- `pyproject.toml` — project metadata, dependencies, and pytest configuration
- `mm/` package scaffold: `__init__.py`, `cli.py`
- `mm/config/` — `schema.py` (v1 event JSON Schema) and `loader.py` (load, validate, slug and uniqueness rules)
- `mm/common/` — `__init__.py`, `io.py`
- `tests/unit/test_config_loader.py` — 53 unit tests covering valid configs, invalid configs, and all validation rules
- `configs/events/` — real event config files

## [0.1.0] - 2026-04-22

### Added

- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `LICENSE`
- `.editorconfig`
- `.prettierrc.js`
- `requirements.txt`
- `README.md`
- `.gitignore`

[Unreleased]: https://github.com/taskarcenteratuw/mapping-momentum/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/taskarcenteratuw/mapping-momentum/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/taskarcenteratuw/mapping-momentum/releases/tag/v0.1.0
