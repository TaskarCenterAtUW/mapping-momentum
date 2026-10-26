"""Tests for secure interactive TDEI credential prompts."""

from __future__ import annotations

import argparse
import builtins
import io
import json
import warnings
from pathlib import Path

import pytest

import mm.cli as cli


class _InteractiveStream(io.StringIO):
    """String stream that reports an interactive terminal."""

    def isatty(self) -> bool:
        return True


def _mock_interactive_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide terminal-like standard streams for prompt tests."""
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveStream())
    monkeypatch.setattr(cli.sys, "stdout", _InteractiveStream())
    monkeypatch.setattr(cli.sys, "stderr", _InteractiveStream())


def _mock_noninteractive_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide non-terminal standard streams for environment credential tests."""
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO())
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())
    monkeypatch.setattr(cli.sys, "stderr", io.StringIO())


def _unexpected_prompt(_prompt: str) -> str:
    """Fail if environment-based authentication tries to prompt."""
    raise AssertionError("Environment credentials must not prompt.")


def test_interactive_authentication_hides_password_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use getpass for the password and pass credentials directly to auth."""
    monkeypatch.delenv("MM_TDEI_USERNAME_PROD", raising=False)
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    _mock_interactive_terminal(monkeypatch)
    prompts: list[str] = []
    credentials: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt: prompts.append(prompt) or " tdei-user ",
    )
    monkeypatch.setattr(
        cli.getpass,
        "getpass",
        lambda prompt: prompts.append(prompt) or "tdei-password",
    )

    def fake_authenticate(environment: str, username: str, password: str) -> str:
        credentials.append((environment, username, password))
        return "short-lived-token"

    monkeypatch.setattr(cli, "authenticate", fake_authenticate)

    token = cli._get_access_token("prod")

    assert token == "short-lived-token"
    assert prompts == [
        "TDEI prod username: ",
        "TDEI prod password: ",
    ]
    assert credentials == [("prod", "tdei-user", "tdei-password")]


def test_interactive_authentication_refuses_non_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail rather than echo a password when no interactive terminal exists."""
    monkeypatch.delenv("MM_TDEI_USERNAME_PROD", raising=False)
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO())
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())
    monkeypatch.setattr(cli.sys, "stderr", io.StringIO())

    with pytest.raises(ValueError, match="interactive terminal") as exc_info:
        cli._get_access_token("prod")
    assert "MM_TDEI_USERNAME_PROD" in str(exc_info.value)
    assert "MM_TDEI_PASSWORD_PROD" in str(exc_info.value)


@pytest.mark.parametrize(
    ("environment", "suffix"),
    [("prod", "PROD"), ("stage", "STAGE"), ("dev", "DEV")],
)
def test_environment_credentials_authenticate_without_terminal(
    environment: str,
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the matching environment pair without prompting or echoing secrets."""
    _mock_noninteractive_terminal(monkeypatch)
    monkeypatch.setenv(f"MM_TDEI_USERNAME_{suffix}", " tdei-user ")
    monkeypatch.setenv(f"MM_TDEI_PASSWORD_{suffix}", " tdei-password ")
    monkeypatch.setattr(builtins, "input", _unexpected_prompt)
    monkeypatch.setattr(cli.getpass, "getpass", _unexpected_prompt)
    credentials: list[tuple[str, str, str]] = []

    def fake_authenticate(env: str, username: str, password: str) -> str:
        credentials.append((env, username, password))
        return "short-lived-token"

    monkeypatch.setattr(cli, "authenticate", fake_authenticate)

    token = cli._get_access_token(environment)

    assert token == "short-lived-token"
    assert credentials == [(environment, "tdei-user", " tdei-password ")]


def test_environment_credentials_must_be_set_as_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject partial credential pairs rather than mixing env and prompt input."""
    _mock_interactive_terminal(monkeypatch)
    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", "tdei-user")
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)

    with pytest.raises(ValueError, match="must be set together") as exc_info:
        cli._get_access_token("prod")

    assert "tdei-user" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("username", "password", "empty_variable"),
    [
        ("", "tdei-password", "MM_TDEI_USERNAME_PROD"),
        ("tdei-user", "", "MM_TDEI_PASSWORD_PROD"),
    ],
)
def test_environment_credentials_reject_empty_values(
    username: str,
    password: str,
    empty_variable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject empty environment credentials and identify only the variable."""
    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", username)
    monkeypatch.setenv("MM_TDEI_PASSWORD_PROD", password)

    with pytest.raises(ValueError, match="cannot be empty") as exc_info:
        cli._get_access_token("prod")

    assert empty_variable in str(exc_info.value)
    assert "tdei-password" not in str(exc_info.value)


def test_interactive_authentication_rejects_echoed_password_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse getpass's insecure fallback when terminal echo cannot be disabled."""
    monkeypatch.delenv("MM_TDEI_USERNAME_PROD", raising=False)
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    _mock_interactive_terminal(monkeypatch)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "tdei-user")

    def echoed_getpass(_prompt: str) -> str:
        warnings.warn("echo fallback", cli.getpass.GetPassWarning)
        return "tdei-password"

    monkeypatch.setattr(cli.getpass, "getpass", echoed_getpass)

    with pytest.raises(ValueError, match="without echo"):
        cli._get_access_token("prod")


def test_event_command_authenticates_once_per_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reuse each environment token across activities in the same event."""
    event_path = tmp_path / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    config = {
        "id": "sample-event",
        "activities": [
            {"id": "walkabout", "environment": "prod"},
            {"id": "rollabout", "environment": "prod"},
        ],
    }
    prompts = []
    runs = []
    monkeypatch.setattr(
        "mm.config.loader.load_event_config",
        lambda _path: config,
    )
    monkeypatch.setattr(
        cli,
        "_get_access_token",
        lambda environment: prompts.append(environment) or "prod-token",
    )
    monkeypatch.setattr(
        "mm.pipeline.run_activity",
        lambda _config, activity, **kwargs: (
            runs.append(
                (
                    activity["id"],
                    kwargs["access_token"],
                    kwargs["anonymize"],
                )
            )
            or {"activity_id": activity["id"]}
        ),
    )

    result = cli._cmd_event(
        argparse.Namespace(
            config=event_path,
            output_dir=tmp_path / "output",
            render_from_stats=None,
            dry_run=True,
            anonymize=True,
        )
    )

    capsys.readouterr()
    assert result == 0
    assert prompts == ["prod"]
    assert runs == [
        ("walkabout", "prod-token", True),
        ("rollabout", "prod-token", True),
    ]


def test_event_parser_accepts_anonymize_flag() -> None:
    """Support both the long and short anonymization options."""
    for option in ("--anonymize", "-a"):
        args = cli._build_parser().parse_args(
            ["event", "--config", "event.json", option]
        )
        assert args.anonymize is True


def test_render_from_stats_anonymizes_report_and_saved_stats(
    tmp_path: Path,
) -> None:
    """Keep both rendered artifacts anonymized without changing source stats."""
    source_stats = {
        "activity_id": "walkabout",
        "contributors_breakdown": [{"user": "alice", "count": 1, "photo_count": 0}],
        "markers": [
            {
                "user": "alice",
                "versions": [{"user": "alice"}],
                "text": "Note from alice",
            }
        ],
        "quotes": [
            {
                "text": "Alex Mapper joined the event.",
                "first_name": "Alex",
                "last_name": "Mapper",
            }
        ],
    }
    stats_path = tmp_path / "source-stats.json"
    stats_path.write_text(json.dumps(source_stats), encoding="utf-8")
    config = {
        "id": "sample-event",
        "name": "Sample Event",
        "activities": [{"id": "walkabout", "label": "Walkabout"}],
    }
    output_dir = tmp_path / "output"

    result = cli._render_from_stats(
        config,
        stats_path,
        output_dir,
        "sample-event",
        anonymize=True,
    )

    assert result == 0
    rendered_dir = output_dir / "events" / "sample-event" / "walkabout"
    output_stats = json.loads((rendered_dir / "stats.json").read_text(encoding="utf-8"))
    html = (rendered_dir / "index.html").read_text(encoding="utf-8")
    assert output_stats["contributors_breakdown"][0]["user"] == "Participant 1"
    assert "alice" not in html
    assert "Participant 1" in html
    assert output_stats["quotes"][0]["first_name"] == "Participant 2"
    assert "Alex Mapper" not in html
    assert "Participant 2" in html
    assert json.loads(stats_path.read_text(encoding="utf-8")) == source_stats
