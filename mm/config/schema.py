"""
mm.config.schema — JSON Schema definitions for Mapping Momentum config files.

This module is the canonical machine-readable schema for v1 configs.
All validation logic references these definitions; there is no second
authoritative source.

v1.1 adds quest_definition_url (required per workspace activity, enforced by
the loader), quest_definition_retrieval_date (optional metadata), report
(optional display overrides), and showcase_photos (optional photo array).
"""

import re

# ---------------------------------------------------------------------------
# Slug pattern — activity.id and event.id must match this.
# Allowed: lowercase letters, digits, and hyphens.
# Must start and end with a letter or digit (no leading/trailing hyphens).
# ---------------------------------------------------------------------------
SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# ---------------------------------------------------------------------------
# Supported schema versions and config types
# ---------------------------------------------------------------------------
SUPPORTED_SCHEMA_VERSIONS = {"1.1"}
SUPPORTED_CONFIG_TYPES = {"event"}  # v1 only; "project" is future

# ---------------------------------------------------------------------------
# Supported activity types (v1: workspace only)
# ---------------------------------------------------------------------------
SUPPORTED_ACTIVITY_TYPES = {"workspace"}  # "tasking_manager" is future

# ---------------------------------------------------------------------------
# Supported workspace environments and their credential env var names
# ---------------------------------------------------------------------------
SUPPORTED_ENVIRONMENTS = {"prod", "stage", "dev"}

# Maps each environment to the environment variable that must hold the TDEI
# API key for that environment.  These are the canonical names used in both
# local development and GitHub Actions secrets.
ENV_CREDENTIAL_VAR: dict[str, str] = {
    "prod": "MM_TDEI_API_KEY_PROD",
    "stage": "MM_TDEI_API_KEY_STAGE",
    "dev": "MM_TDEI_API_KEY_DEV",
}

# ---------------------------------------------------------------------------
# JSON Schema — top-level event config
# ---------------------------------------------------------------------------
TIME_WINDOW_SCHEMA: dict = {
    "type": "object",
    "required": ["start", "end"],
    "additionalProperties": False,
    "properties": {
        "start": {
            "type": "string",
            "description": "ISO 8601 UTC timestamp for the start of this window.",
        },
        "end": {
            "type": "string",
            "description": "ISO 8601 UTC timestamp for the end of this window.",
        },
    },
}

WORKSPACE_ACTIVITY_SCHEMA: dict = {
    "type": "object",
    "required": [
        "id",
        "type",
        "project_group_id",
        "workspace_id",
        "environment",
        "time_window",
    ],
    "additionalProperties": False,
    "properties": {
        "id": {
            "type": "string",
            "description": "Slug-safe activity identifier (used in output paths).",
        },
        "type": {
            "type": "string",
            "const": "workspace",
        },
        "label": {
            "type": "string",
            "description": "Human-readable display label for the activity.",
        },
        "project_group_id": {
            "type": "string",
            "description": (
                "TDEI project group UUID. Stored as metadata to document"
                " which project group this workspace belongs to. Not used"
                " for API key lookup — access is granted by manually adding"
                " the Mapping Momentum TDEI account to the project group."
            ),
        },
        "workspace_id": {
            "type": "integer",
            "description": "TDEI Workspace ID (integer).",
        },
        "environment": {
            "type": "string",
            "enum": list(SUPPORTED_ENVIRONMENTS),
            "description": "TDEI API environment (prod, stage, or dev). Required.",
        },
        "time_window": TIME_WINDOW_SCHEMA,
        # New in v1.1 — optional in JSON Schema; loader enforces required for 1.1.
        "quest_definition_url": {
            "type": "string",
            "description": (
                "Raw URL of the upstream asr-quests quest definition file."
                " Written by capture-quests; report runs read only the"
                " committed quest-definition.json cache."
            ),
        },
        "quest_definition_retrieval_date": {
            "type": "string",
            "description": (
                "UTC ISO 8601 datetime when capture-quests last refreshed"
                " the committed quest-definition.json cache."
                " Set automatically; never set manually."
            ),
        },
    },
}


# ---------------------------------------------------------------------------
# v1.1 optional top-level objects
# ---------------------------------------------------------------------------

REPORT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {
            "type": "string",
            "description": "Report page title; defaults to event name.",
        },
        "subtitle": {
            "type": "string",
            "description": (
                "Report subtitle; defaults to '<date> · <activity label>'."
            ),
        },
    },
}

SHOWCASE_PHOTO_SCHEMA: dict = {
    "type": "object",
    "required": ["src"],
    "additionalProperties": False,
    "properties": {
        "src": {
            "type": "string",
            "description": (
                "URL or path relative to the event directory."
                " Relative paths are resolved and validated at load time."
            ),
        },
        "caption": {
            "type": "string",
            "description": "Optional caption displayed beneath the photo.",
        },
    },
}

# v1: only workspace activities are allowed; the schema uses oneOf so that
# future activity types can be added here without restructuring.
ACTIVITY_SCHEMA: dict = {
    "oneOf": [WORKSPACE_ACTIVITY_SCHEMA],
}

EVENT_CONFIG_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["schema_version", "type", "id", "name", "date", "activities"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {
            "type": "string",
            "enum": sorted(SUPPORTED_SCHEMA_VERSIONS),
        },
        "type": {
            "type": "string",
            "const": "event",
        },
        "id": {
            "type": "string",
            "description": "Slug-safe event identifier (used in output paths).",
        },
        "name": {
            "type": "string",
            "description": "Human-readable event name.",
        },
        "date": {
            "type": "string",
            "description": "Primary date of the event in YYYY-MM-DD format.",
        },
        "activities": {
            "type": "array",
            "minItems": 1,
            "items": ACTIVITY_SCHEMA,
        },
        # New in v1.1 — optional in both versions.
        "report": REPORT_SCHEMA,
        "showcase_photos": {
            "type": "array",
            "items": SHOWCASE_PHOTO_SCHEMA,
            "description": "Participant photos shown in the report hero strip.",
        },
    },
}
