"""Focused side-effect-free tests for local report publication."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import mm.publication as publication
from mm.publication import (
    PRIVACY_AFFIRMATION,
    PublicationError,
    approve_and_push_publication,
)


def _completed(
    arguments: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        arguments,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _candidate(repo: Path, sha: str, beta_parent_sha: str | None) -> None:
    result_path = publication.candidate_check_path(repo, sha)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps({"success": True, "sha": sha}),
        encoding="utf-8",
    )
    candidate_path = (
        repo / "local-storage" / "publication-candidates" / sha / "candidate.json"
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps({"sha": sha, "beta_parent_sha": beta_parent_sha}),
        encoding="utf-8",
    )


def _event_config(repo: Path, event_id: str, *, publish: bool = True) -> None:
    path = repo / "configs" / "events" / event_id / "event.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "type": "event",
                "id": event_id,
                "name": event_id,
                "date": event_id[:10],
                "publish": publish,
                "activities": [
                    {
                        "id": "walkabout",
                        "type": "workspace",
                        "label": "Walkabout",
                        "project_group_id": ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                        "workspace_id": 1,
                        "environment": "prod",
                        "quest_definition_url": "https://example.com/quest.json",
                        "time_window": {
                            "start": f"{event_id[:10]}T10:00:00Z",
                            "end": f"{event_id[:10]}T12:00:00Z",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_anonymized_report(
    anonymized_root: Path,
    relative_path: str,
) -> Path:
    report_path = anonymized_root / relative_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html></html>\n", encoding="utf-8")
    return report_path


def _configure_approval_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo_root: Path,
    candidate_sha: str,
    remote_beta: list[str | None],
    ancestor: bool = True,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def fake_run_git(
        actual_repo: Path,
        arguments: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        assert actual_repo.resolve() == repo_root.resolve()
        calls.append(tuple(arguments))
        if arguments and arguments[0] == "ls-remote":
            assert check
            assert arguments[-1] == "refs/heads/beta"
            remote_sha = remote_beta.pop(0)
            stdout = f"{remote_sha}\trefs/heads/beta\n" if remote_sha else ""
            return _completed(arguments, stdout=stdout)
        if arguments[:2] == ["rev-parse", "--verify"]:
            assert not check
            return _completed(arguments, stdout=f"{candidate_sha}\n")
        if arguments[:2] == ["cat-file", "-e"]:
            assert not check
            return _completed(arguments)
        if arguments[:2] == ["merge-base", "--is-ancestor"]:
            assert not check
            return _completed(arguments, returncode=0 if ancestor else 1)
        if arguments and arguments[0] == "fetch":
            assert not check
            return _completed(arguments)
        return _completed(arguments)

    monkeypatch.setattr(publication, "run_git", fake_run_git)
    return calls


def _configure_prepare_fakes(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    *,
    unexpected_file: str | None = None,
) -> list[tuple[str, set[str]]]:
    repo_root = repo_root.resolve()
    staged_snapshots: list[tuple[str, set[str]]] = []

    def fake_generate_golden_sample(
        actual_repo_root: Path,
        staging_dir: Path,
    ) -> None:
        assert actual_repo_root == repo_root
        golden_report = staging_dir / "golden-sample" / "index.html"
        golden_report.parent.mkdir(parents=True, exist_ok=True)
        golden_report.write_text("<html>sample</html>\n", encoding="utf-8")
        if unexpected_file is not None:
            unexpected = staging_dir / unexpected_file
            unexpected.parent.mkdir(parents=True, exist_ok=True)
            unexpected.write_text("unexpected\n", encoding="utf-8")

    def fake_run_git(
        working_tree: Path,
        arguments: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if arguments and arguments[0] == "ls-remote":
            assert working_tree == repo_root
            assert check
            return _completed(arguments)
        if arguments[:2] == ["worktree", "add"]:
            worktree = Path(arguments[3])
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text("gitdir: metadata\n", encoding="utf-8")
            stale = worktree / "old" / "report.html"
            stale.parent.mkdir()
            stale.write_text("stale\n", encoding="utf-8")
        if arguments[:2] == ["add", "-A"]:
            assert (working_tree / ".git").is_file()
            assert not (working_tree / "old").exists()
            assert (working_tree / "index.html").is_file()
            staged_files = {
                path.relative_to(working_tree).as_posix()
                for path in working_tree.rglob("*")
                if path.is_file() and path.name != ".git"
            }
            staged_snapshots.append(
                (
                    (working_tree / "index.html").read_text(encoding="utf-8"),
                    staged_files,
                )
            )
        if arguments[:3] == ["diff", "--cached", "--quiet"]:
            assert not check
            return _completed(arguments, returncode=1)
        if arguments[:2] == ["rev-parse", "HEAD"]:
            return _completed(arguments, stdout=f"{'f' * 40}\n")
        if arguments[:2] == ["worktree", "remove"]:
            assert not check
        return _completed(arguments)

    monkeypatch.setattr(publication, "run_git", fake_run_git)
    monkeypatch.setattr(
        publication,
        "_generate_golden_sample",
        fake_generate_golden_sample,
    )
    return staged_snapshots


def test_approval_bootstraps_absent_beta_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An initial candidate may create beta, but the push remains non-forcing."""
    sha = "a" * 40
    _candidate(tmp_path, sha, None)
    calls = _configure_approval_fakes(
        monkeypatch,
        repo_root=tmp_path,
        candidate_sha=sha,
        remote_beta=[None, sha],
    )

    assert (
        approve_and_push_publication(
            tmp_path,
            sha,
            affirmation=PRIVACY_AFFIRMATION,
        )
        == sha
    )
    push = next(call for call in calls if call[0] == "push")
    assert all("--force" not in argument for argument in push)
    assert push[-1] == f"{sha}:refs/heads/beta"


def test_approval_rejects_beta_that_advanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ancestor beta tip requires a newly prepared candidate."""
    sha = "a" * 40
    parent = "b" * 40
    current = "c" * 40
    _candidate(tmp_path, sha, parent)
    _configure_approval_fakes(
        monkeypatch,
        repo_root=tmp_path,
        candidate_sha=sha,
        remote_beta=[current],
        ancestor=False,
    )

    with pytest.raises(PublicationError, match="advanced since preparation"):
        approve_and_push_publication(
            tmp_path,
            sha,
            affirmation=PRIVACY_AFFIRMATION,
        )


def test_approval_rejects_beta_appearing_after_parentless_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A branch race invalidates a candidate prepared for first publication."""
    sha = "a" * 40
    current = "b" * 40
    _candidate(tmp_path, sha, None)
    _configure_approval_fakes(
        monkeypatch,
        repo_root=tmp_path,
        candidate_sha=sha,
        remote_beta=[current],
    )

    with pytest.raises(PublicationError, match="appeared after preparation"):
        approve_and_push_publication(
            tmp_path,
            sha,
            affirmation=PRIVACY_AFFIRMATION,
        )


def test_prepare_publication_replaces_stale_worktree_files_but_keeps_git_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preparing a snapshot replaces old reports without removing Git metadata."""
    event_id = "2026-01-01-cleanup"
    _event_config(tmp_path, event_id)
    anonymized_root = tmp_path / "anonymized"
    _write_anonymized_report(
        anonymized_root,
        f"events/{event_id}/walkabout/index.html",
    )
    _configure_prepare_fakes(monkeypatch, tmp_path)

    prepared = publication.prepare_publication(tmp_path, anonymized_root)

    assert prepared.sha == "f" * 40


def test_prepare_publication_index_uses_published_configs_and_omits_golden_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The staged index includes published reports, not drafts or Golden Sample."""
    event_ids = ["2026-01-01-nda-one", "2026-01-02-nda-two"]
    for event_id in event_ids:
        _event_config(tmp_path, event_id)
    _event_config(tmp_path, "2026-01-03-draft-hidden", publish=False)
    anonymized_root = tmp_path / "anonymized"
    for event_id in event_ids:
        _write_anonymized_report(
            anonymized_root,
            f"events/{event_id}/walkabout/index.html",
        )
    _write_anonymized_report(
        anonymized_root,
        "events/aggregates/nda/index.html",
    )
    staged_snapshots = _configure_prepare_fakes(monkeypatch, tmp_path)

    prepared = publication.prepare_publication(tmp_path, anonymized_root)
    assert prepared.staging_directory is not None
    assert (prepared.staging_directory / "candidate.json").is_file()
    assert len(staged_snapshots) == 1
    index, staged_files = staged_snapshots[0]
    assert "events/2026-01-01-nda-one/walkabout/index.html" in index
    assert "events/2026-01-02-nda-two/walkabout/index.html" in index
    assert "events/aggregates/nda/index.html" in index
    assert "2026-01-03-draft-hidden" not in index
    assert "golden-sample" not in index
    assert "golden-sample/index.html" in staged_files


@pytest.mark.parametrize("value", [None, 42])
def test_full_sha_rejects_non_string_values(value: object) -> None:
    """Reject malformed SHA inputs with the publication error contract."""
    with pytest.raises(PublicationError, match="full hexadecimal"):
        publication.full_sha(value)


@pytest.mark.parametrize("kind", ["missing", "symlink"])
def test_safe_staging_copy_rejects_unsafe_input(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publication rejects missing and symlinked report inputs."""
    event_id = "2026-01-01-unsafe"
    _event_config(tmp_path, event_id)
    anonymized_root = tmp_path / "anonymized"
    source = anonymized_root / f"events/{event_id}/walkabout/index.html"
    if kind == "symlink":
        _write_anonymized_report(
            anonymized_root,
            f"events/{event_id}/walkabout/index.html",
        )
        original_is_symlink = Path.is_symlink

        def fake_is_symlink(path: Path) -> bool:
            return path == source or original_is_symlink(path)

        monkeypatch.setattr(
            Path,
            "is_symlink",
            fake_is_symlink,
        )

    with pytest.raises(PublicationError, match=kind):
        publication.prepare_publication(tmp_path, anonymized_root)


def test_prepare_publication_rejects_destination_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed allowlist destination cannot escape the staging root."""
    source = tmp_path / "source.html"
    source.write_text("<html></html>\n", encoding="utf-8")
    anonymized_root = tmp_path / "anonymized"

    def unsafe_allowlist(
        repo_root: Path,
        expected_anonymized_root: Path,
    ) -> tuple[list[tuple[Path, str]], list[str]]:
        assert repo_root == tmp_path.resolve()
        assert expected_anonymized_root == anonymized_root.resolve()
        return [(source, "../escape.html")], [
            "index.html",
            "golden-sample/index.html",
            ".nojekyll",
        ]

    monkeypatch.setattr(publication, "publication_allowlist", unsafe_allowlist)

    with pytest.raises(PublicationError, match="escapes staging"):
        publication.prepare_publication(tmp_path, anonymized_root)


def test_prepare_publication_rejects_unexpected_staged_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected files generated during preparation block the snapshot."""
    event_id = "2026-01-01-unexpected"
    _event_config(tmp_path, event_id)
    anonymized_root = tmp_path / "anonymized"
    _write_anonymized_report(
        anonymized_root,
        f"events/{event_id}/walkabout/index.html",
    )
    _configure_prepare_fakes(
        monkeypatch,
        tmp_path,
        unexpected_file="unexpected.json",
    )

    with pytest.raises(PublicationError, match=r"unexpected: unexpected\.json"):
        publication.prepare_publication(tmp_path, anonymized_root)


def test_approval_requires_exact_privacy_affirmation(tmp_path: Path) -> None:
    """Programmatic publication callers must provide the exact review statement."""
    with pytest.raises(PublicationError, match="exact privacy affirmation"):
        approve_and_push_publication(
            tmp_path,
            "a" * 40,
            affirmation="Yes",
        )
