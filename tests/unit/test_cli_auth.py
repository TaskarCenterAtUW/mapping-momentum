"""Tests for secure interactive TDEI credential prompts."""

from __future__ import annotations

import builtins
import io
import json
import warnings
from pathlib import Path
from typing import Any

import pytest

import mm.cli as cli
from mm.publication import (
    PRIVACY_AFFIRMATION,
    PublicationError,
    approve_and_push_publication,
)


class _InteractiveStream(io.StringIO):
    """String stream that reports an interactive terminal."""

    def isatty(self) -> bool:
        return True


def _mock_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_InteractiveStream, _InteractiveStream, _InteractiveStream]:
    """Provide terminal-like standard streams for prompt tests."""
    stdin = _InteractiveStream()
    stdout = _InteractiveStream()
    stderr = _InteractiveStream()
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    return stdin, stdout, stderr


def _mock_noninteractive_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[io.StringIO, io.StringIO, io.StringIO]:
    """Provide non-terminal standard streams for environment credential tests."""
    stdin = io.StringIO()
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    return stdin, stdout, stderr


def _unexpected_prompt(_: str) -> str:
    """Fail if environment-based authentication tries to prompt."""
    raise AssertionError("Environment credentials must not prompt.")


def _event_config(*environments: str) -> dict[str, Any]:
    """Create a minimal event config for public CLI tests."""
    return {
        "id": "sample-event",
        "name": "Sample Event",
        "activities": [
            {
                "id": f"activity-{index}",
                "label": f"Activity {index}",
                "environment": environment,
            }
            for index, environment in enumerate(environments, start=1)
        ],
    }


def _stub_event_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    config: dict[str, Any],
) -> tuple[Path, list[tuple[str, str, bool, bool]]]:
    """Stub config loading and activity execution for the public CLI."""
    event_path = tmp_path / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    runs: list[tuple[str, str, bool, bool]] = []

    def load_event_config(path: Path) -> dict[str, Any]:
        assert path == event_path
        return config

    def run_activity(
        event_config: dict[str, Any],
        activity: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert event_config is config
        activity_id = activity.get("id")
        access_token = kwargs.get("access_token")
        anonymize = kwargs.get("anonymize")
        include_quest_answer_log = kwargs.get("include_quest_answer_log")
        assert isinstance(activity_id, str)
        assert isinstance(access_token, str)
        assert isinstance(anonymize, bool)
        assert isinstance(include_quest_answer_log, bool)
        runs.append((activity_id, access_token, anonymize, include_quest_answer_log))
        return {"activity_id": activity_id}

    monkeypatch.setattr(
        "mm.config.loader.load_event_config",
        load_event_config,
    )
    monkeypatch.setattr("mm.pipeline.run_activity", run_activity)
    return event_path, runs


def _stub_publication_api(
    monkeypatch: pytest.MonkeyPatch,
    sha: str,
) -> list[str]:
    """Stub the successful-check lookup and beta push for CLI tests."""
    pushed_shas: list[str] = []
    expected_repo_root = Path(cli.__file__).resolve().parents[1]

    def read_check(repo_root: Path, requested_sha: str) -> dict[str, Any]:
        assert repo_root == expected_repo_root
        assert requested_sha == sha
        return {"sha": requested_sha}

    def approve(
        repo_root: Path,
        approved_sha: str,
        *,
        affirmation: str,
        remote_name: str = "origin",
    ) -> str:
        assert repo_root == expected_repo_root
        assert approved_sha == sha
        assert affirmation == PRIVACY_AFFIRMATION
        assert remote_name == "origin"
        pushed_shas.append(approved_sha)
        return approved_sha

    monkeypatch.setattr("mm.publication.read_successful_check", read_check)
    monkeypatch.setattr(
        "mm.publication.approve_and_push_publication",
        approve,
    )
    return pushed_shas


@pytest.mark.parametrize("answer", [PRIVACY_AFFIRMATION])
def test_interactive_beta_approval_accepts_exact_affirmation(
    answer: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public command accepts the exact privacy-review affirmation."""
    _mock_interactive_terminal(monkeypatch)
    sha = "a" * 40
    prompts: list[str] = []

    def answer_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return answer

    monkeypatch.setattr(builtins, "input", answer_prompt)
    pushed_shas = _stub_publication_api(monkeypatch, sha)

    result = cli.run_cli(["publish", "approve", "--sha", sha])

    assert result == 0
    assert pushed_shas == [sha]
    assert prompts == [
        f"Reviewed beta SHA: {sha}\n"
        "Type the following exactly before the public beta push:\n"
        f"{PRIVACY_AFFIRMATION}\n> "
    ]


@pytest.mark.parametrize("answer", ["", "y", "yes", f" {PRIVACY_AFFIRMATION}"])
def test_interactive_beta_approval_defaults_to_no(
    answer: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incomplete or altered affirmations cancel without pushing."""
    _mock_interactive_terminal(monkeypatch)
    sha = "a" * 40
    pushed_shas = _stub_publication_api(monkeypatch, sha)

    def answer_prompt(_: str) -> str:
        return answer

    monkeypatch.setattr(builtins, "input", answer_prompt)

    assert cli.run_cli(["publish", "approve", "--sha", sha]) == 0
    assert pushed_shas == []


def test_interactive_beta_approval_refuses_non_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public command fails closed without an interactive terminal."""
    _, _, stderr = _mock_noninteractive_terminal(monkeypatch)
    sha = "a" * 40
    pushed_shas = _stub_publication_api(monkeypatch, sha)

    result = cli.run_cli(["publish", "approve", "--sha", sha])

    assert result == 1
    assert "interactive terminal" in stderr.getvalue()
    assert pushed_shas == []


def test_publish_approve_rejects_command_line_affirmation() -> None:
    """The public CLI does not accept a pre-supplied privacy affirmation."""
    with pytest.raises(SystemExit) as exc_info:
        cli.run_cli(
            [
                "publish",
                "approve",
                "--sha",
                "a" * 40,
                "--affirmation",
                PRIVACY_AFFIRMATION,
            ]
        )

    assert exc_info.value.code == 2


def test_publication_api_rejects_unconfirmed_approval(
    tmp_path: Path,
) -> None:
    """Do not push through the publication API without explicit confirmation."""
    with pytest.raises(PublicationError, match="exact privacy affirmation"):
        approve_and_push_publication(
            tmp_path,
            "a" * 40,
            affirmation="yes",
        )


def test_interactive_authentication_hides_password_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The event CLI hides the password and forwards credentials to auth."""
    event_path, runs = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.delenv("MM_TDEI_USERNAME_PROD", raising=False)
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    _mock_interactive_terminal(monkeypatch)
    prompts: list[str] = []
    credentials: list[tuple[str, str, str]] = []

    def answer_username(prompt: str) -> str:
        prompts.append(prompt)
        return " tdei-user "

    def answer_password(prompt: str) -> str:
        prompts.append(prompt)
        return "tdei-password"

    def fake_authenticate(environment: str, username: str, password: str) -> str:
        credentials.append((environment, username, password))
        return "short-lived-token"

    monkeypatch.setattr(builtins, "input", answer_username)
    monkeypatch.setattr(cli.getpass, "getpass", answer_password)
    monkeypatch.setattr(cli, "authenticate", fake_authenticate)

    result = cli.run_cli(["event", "--config", str(event_path), "--dry-run"])

    assert result == 0
    assert prompts == [
        "TDEI prod username: ",
        "TDEI prod password: ",
    ]
    assert credentials == [("prod", "tdei-user", "tdei-password")]
    assert runs == [("activity-1", "short-lived-token", False, False)]


def test_interactive_authentication_refuses_non_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The event CLI refuses credentials when no terminal is available."""
    event_path, _ = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.delenv("MM_TDEI_USERNAME_PROD", raising=False)
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    _, _, stderr = _mock_noninteractive_terminal(monkeypatch)

    result = cli.run_cli(["event", "--config", str(event_path), "--dry-run"])

    assert result == 1
    assert "interactive terminal" in stderr.getvalue()
    assert "MM_TDEI_USERNAME_PROD" in stderr.getvalue()
    assert "MM_TDEI_PASSWORD_PROD" in stderr.getvalue()


@pytest.mark.parametrize(
    ("environment", "suffix"),
    [("prod", "PROD"), ("stage", "STAGE"), ("dev", "DEV")],
)
def test_environment_credentials_authenticate_without_terminal(
    environment: str,
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use the matching environment pair without prompting or echoing secrets."""
    event_path, runs = _stub_event_command(
        monkeypatch, tmp_path, _event_config(environment)
    )
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

    result = cli.run_cli(["event", "--config", str(event_path), "--dry-run"])

    assert result == 0
    assert credentials == [(environment, "tdei-user", " tdei-password ")]
    assert runs == [("activity-1", "short-lived-token", False, False)]


def test_environment_credentials_must_be_set_as_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject partial credential pairs rather than mixing env and prompt input."""
    event_path, _ = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", "tdei-user")
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    _, _, stderr = _mock_interactive_terminal(monkeypatch)

    result = cli.run_cli(["event", "--config", str(event_path), "--dry-run"])

    assert result == 1
    assert "must be set together" in stderr.getvalue()
    assert "tdei-user" not in stderr.getvalue()


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
    tmp_path: Path,
) -> None:
    """Reject empty environment credentials and identify only the variable."""
    event_path, _ = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", username)
    monkeypatch.setenv("MM_TDEI_PASSWORD_PROD", password)
    _, _, stderr = _mock_noninteractive_terminal(monkeypatch)

    result = cli.run_cli(["event", "--config", str(event_path), "--dry-run"])

    assert result == 1
    assert empty_variable in stderr.getvalue()
    assert "tdei-password" not in stderr.getvalue()


def test_interactive_authentication_rejects_echoed_password_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Refuse getpass's insecure fallback when terminal echo cannot be disabled."""
    event_path, _ = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.delenv("MM_TDEI_USERNAME_PROD", raising=False)
    monkeypatch.delenv("MM_TDEI_PASSWORD_PROD", raising=False)
    _, _, stderr = _mock_interactive_terminal(monkeypatch)

    def answer_username(prompt: str) -> str:
        assert prompt == "TDEI prod username: "
        return "tdei-user"

    def echoed_getpass(prompt: str) -> str:
        assert prompt == "TDEI prod password: "
        warnings.warn("echo fallback", cli.getpass.GetPassWarning)
        return "tdei-password"

    monkeypatch.setattr(builtins, "input", answer_username)
    monkeypatch.setattr(cli.getpass, "getpass", echoed_getpass)

    result = cli.run_cli(["event", "--config", str(event_path), "--dry-run"])

    assert result == 1
    assert "without echo" in stderr.getvalue()


def test_event_command_authenticates_once_per_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reuse each environment token across activities in the same event."""
    config = _event_config("prod", "prod")
    event_path, runs = _stub_event_command(monkeypatch, tmp_path, config)

    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", "tdei-user")
    monkeypatch.setenv("MM_TDEI_PASSWORD_PROD", "tdei-password")
    _mock_noninteractive_terminal(monkeypatch)
    monkeypatch.setattr(builtins, "input", _unexpected_prompt)
    monkeypatch.setattr(cli.getpass, "getpass", _unexpected_prompt)
    credentials: list[tuple[str, str, str]] = []

    def fake_authenticate(environment: str, username: str, password: str) -> str:
        credentials.append((environment, username, password))
        return "prod-token"

    monkeypatch.setattr(cli, "authenticate", fake_authenticate)

    result = cli.run_cli(
        [
            "event",
            "--config",
            str(event_path),
            "--dry-run",
            "--anonymize",
            "--quest-answer-log",
        ]
    )

    assert result == 0
    assert credentials == [("prod", "tdei-user", "tdei-password")]
    assert runs == [
        ("activity-1", "prod-token", True, True),
        ("activity-2", "prod-token", True, True),
    ]


def test_event_parser_accepts_quest_answer_log_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public event command forwards opt-in and default answer-log values."""
    event_path, runs = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", "tdei-user")
    monkeypatch.setenv("MM_TDEI_PASSWORD_PROD", "tdei-password")
    _mock_noninteractive_terminal(monkeypatch)

    def fake_authenticate(environment: str, username: str, password: str) -> str:
        assert (environment, username, password) == (
            "prod",
            "tdei-user",
            "tdei-password",
        )
        return "prod-token"

    monkeypatch.setattr(cli, "authenticate", fake_authenticate)
    base_args = ["event", "--config", str(event_path), "--dry-run"]
    assert cli.run_cli([*base_args, "--quest-answer-log"]) == 0
    assert cli.run_cli(base_args) == 0
    assert [run[3] for run in runs] == [True, False]


def test_event_command_rejects_answer_log_with_render_from_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Avoid silently omitting the log when only rendering saved stats."""
    event_path, _ = _stub_event_command(monkeypatch, tmp_path, _event_config())

    result = cli.run_cli(
        [
            "event",
            "--config",
            str(event_path),
            "--render-from-stats",
            str(tmp_path / "stats.json"),
            "--quest-answer-log",
        ]
    )

    assert result == 1
    assert "--quest-answer-log" in capsys.readouterr().err


def test_event_parser_accepts_anonymize_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public event command supports both anonymization options."""
    event_path, runs = _stub_event_command(monkeypatch, tmp_path, _event_config("prod"))
    monkeypatch.setenv("MM_TDEI_USERNAME_PROD", "tdei-user")
    monkeypatch.setenv("MM_TDEI_PASSWORD_PROD", "tdei-password")
    _mock_noninteractive_terminal(monkeypatch)

    def fake_authenticate(environment: str, username: str, password: str) -> str:
        assert (environment, username, password) == (
            "prod",
            "tdei-user",
            "tdei-password",
        )
        return "prod-token"

    monkeypatch.setattr(cli, "authenticate", fake_authenticate)
    base_args = ["event", "--config", str(event_path), "--dry-run"]
    for option in ("--anonymize", "-a"):
        assert cli.run_cli([*base_args, option]) == 0

    assert [run[2] for run in runs] == [True, True]


def test_render_from_stats_anonymizes_report_and_saved_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep both rendered artifacts anonymized without changing source stats."""
    source_stats: dict[str, Any] = {
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
    config: dict[str, Any] = {
        "id": "sample-event",
        "name": "Sample Event",
        "activities": [{"id": "walkabout", "label": "Walkabout"}],
    }
    event_path, runs = _stub_event_command(monkeypatch, tmp_path, config)
    output_dir = tmp_path / "output"

    result = cli.run_cli(
        [
            "event",
            "--config",
            str(event_path),
            "--render-from-stats",
            str(stats_path),
            "--output-dir",
            str(output_dir),
            "--anonymize",
        ]
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
    assert runs == []


@pytest.mark.parametrize(
    ("stats_data", "message"),
    [
        ("[]", "stats.json must contain a JSON object"),
        ('{"activity_id": 123}', "stats.json activity_id must be a string"),
    ],
)
def test_render_from_stats_rejects_invalid_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stats_data: str,
    message: str,
) -> None:
    stats_path = tmp_path / "stats.json"
    stats_path.write_text(stats_data, encoding="utf-8")
    config: dict[str, Any] = {
        "id": "sample-event",
        "name": "Sample Event",
        "activities": [{"id": "walkabout", "label": "Walkabout"}],
    }
    event_path, runs = _stub_event_command(monkeypatch, tmp_path, config)

    result = cli.run_cli(
        [
            "event",
            "--config",
            str(event_path),
            "--render-from-stats",
            str(stats_path),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )

    assert result == 1
    assert message in capsys.readouterr().err
    assert runs == []
