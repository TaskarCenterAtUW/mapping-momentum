---
description: Project-wide instructions for the Mapping Momentum workspace
applyTo: "**"
---

<!-- @format -->

IMPORTANT: This project uses **uv** for package management with a Python virtual environment (`.venv/`). ALWAYS run `.\.venv\Scripts\Activate.ps1` before ANY terminal command (python, pytest, ruff, utility scripts, etc.). To install or update dependencies, run `uv sync --group dev`. Never assume the venv is already activated.

## Version Control

- Use [Conventional Commits](https://www.conventionalcommits.org/), [Semantic Versioning](https://semver.org/), and [Keep a Changelog](https://keepachangelog.com/).
- Commit prefixes: `feat`, `fix`, `docs`, `chore`.
- For each release-worthy change set, update `CHANGELOG.md` and the `version` field in the root `pyproject.toml`.
