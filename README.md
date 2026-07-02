<!-- @format -->

# Mapping Momentum

Statistics engine and report generator for tracking mapping participation metrics.

## Overview

Mapping Momentum generates per-activity stats and a minimal HTML report from a v1 event config. The initial release is scoped to `workspace` activities only.

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

```powershell
$env:MM_TDEI_API_KEY_PROD = 'test-api-key'
mapping-momentum event --config configs/events/nda-vancouver/event.json
```

The CLI currently validates and loads the config. The fetch, metrics, and report-rendering pipeline will be added in later slices.
