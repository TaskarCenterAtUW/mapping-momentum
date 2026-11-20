"""Focused side-effect-free tests for stable snapshot promotion."""

from __future__ import annotations

import subprocess
from typing import TypedDict

import pytest

from utilities import promote_snapshot


class _PromotionState(TypedDict):
    pushes: int
    lease: str
    remote_stable: str | None
    created: list[tuple[str, str | None, str]]
    push_failure: bool


def _completed(
    arguments: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(arguments, returncode, stdout=stdout, stderr="")


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidate: str,
    beta_tip: str,
    stable_tip: str | None,
    last_promoted: str | None = None,
    ancestry: dict[tuple[str, str], bool] | None = None,
    candidate_tree: str = "candidate-tree",
    stable_tree: str = "stable-tree",
) -> _PromotionState:
    state: _PromotionState = {
        "pushes": 0,
        "lease": "",
        "remote_stable": stable_tip,
        "created": [],
        "push_failure": False,
    }

    def fake_run_git(
        arguments: list[str],
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if arguments[:2] == ["cat-file", "-e"]:
            assert not check
            return _completed(arguments)
        if arguments and arguments[0] == "push":
            assert not check
            assert env is not None
            state["pushes"] += 1
            state["lease"] = arguments[2]
            if state.get("push_failure"):
                return _completed(arguments, returncode=1)
            state["remote_stable"] = arguments[-1].split(":", 1)[0]
            return _completed(arguments)
        return _completed(arguments)

    branches: dict[str, str | None] = {
        "beta": beta_tip,
        "stable": stable_tip,
    }

    def remote_sha(branch: str) -> str | None:
        value = branches[branch]
        if branch == "stable" and state["pushes"]:
            value = state["remote_stable"]
        return value

    def is_ancestor(ancestor: str, descendant: str) -> bool:
        return (ancestry or {}).get((ancestor, descendant), ancestor == descendant)

    def tree_sha(sha: str) -> str:
        if sha == candidate:
            return candidate_tree
        if sha == stable_tip or sha.startswith("new-stable"):
            return candidate_tree
        return stable_tree

    def create_stable(candidate_sha: str, parent: str | None) -> str:
        created = f"new-stable-{candidate_sha[:8]}"
        state["created"].append((candidate_sha, parent, created))
        return created

    monkeypatch.setattr(promote_snapshot, "_run_git", fake_run_git)
    monkeypatch.setattr(promote_snapshot, "_remote_sha", remote_sha)
    monkeypatch.setattr(promote_snapshot, "_is_ancestor", is_ancestor)
    monkeypatch.setattr(promote_snapshot, "_tree_sha", tree_sha)
    monkeypatch.setattr(promote_snapshot, "_create_stable_commit", create_stable)

    def read_promoted_sha(stable_sha: str) -> str:
        assert stable_sha == state["remote_stable"]
        return last_promoted or ""

    monkeypatch.setattr(promote_snapshot, "_read_promoted_sha", read_promoted_sha)
    return state


def test_promotes_reachable_non_tip_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reviewed ancestor remains eligible after beta advances."""
    candidate = "a" * 40
    beta_tip = "b" * 40
    state = _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip=beta_tip,
        stable_tip=None,
        ancestry={(candidate, beta_tip): True},
    )

    stable = promote_snapshot.promote(candidate, rollback=False)

    assert stable.startswith("new-stable")
    assert state["pushes"] == 1
    assert state["lease"] == "--force-with-lease=refs/heads/stable:"


def test_rejects_commit_not_reachable_from_beta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit outside fetched beta ancestry is not promotable."""
    candidate = "a" * 40
    state = _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip="b" * 40,
        stable_tip=None,
        ancestry={(candidate, "b" * 40): False},
    )

    with pytest.raises(
        promote_snapshot.PromotionError,
        match="not reachable from remote beta",
    ):
        promote_snapshot.promote(candidate, rollback=False)
    assert state["pushes"] == 0


def test_idempotent_promotion_reuses_exact_stable_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same beta SHA verifies the existing stable release without pushing."""
    candidate = "a" * 40
    stable_tip = "c" * 40
    state = _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip=candidate,
        stable_tip=stable_tip,
        last_promoted=candidate,
    )

    assert promote_snapshot.promote(candidate, rollback=False) == stable_tip
    assert state["pushes"] == 0


def test_older_promotion_requires_explicit_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older ancestor is rejected unless rollback is explicitly enabled."""
    candidate = "a" * 40
    last_promoted = "b" * 40
    _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip=last_promoted,
        stable_tip="c" * 40,
        last_promoted=last_promoted,
        ancestry={(candidate, last_promoted): True, (last_promoted, candidate): False},
    )

    with pytest.raises(promote_snapshot.PromotionError, match="rollback=true"):
        promote_snapshot.promote(candidate, rollback=False)

    assert promote_snapshot.promote(candidate, rollback=True).startswith("new-stable")


def test_rejects_divergent_candidate_even_with_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback cannot override divergent beta histories."""
    candidate = "a" * 40
    last_promoted = "b" * 40
    state = _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip="c" * 40,
        stable_tip="d" * 40,
        last_promoted=last_promoted,
        ancestry={
            (candidate, "c" * 40): True,
            (last_promoted, candidate): False,
            (candidate, last_promoted): False,
        },
    )

    with pytest.raises(promote_snapshot.PromotionError, match="diverges"):
        promote_snapshot.promote(candidate, rollback=True)
    assert state["pushes"] == 0


def test_compare_and_swap_reports_concurrent_stable_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed stable ref makes the guarded push fail closed."""
    candidate = "a" * 40
    last_promoted = "b" * 40
    stable_tip = "c" * 40
    state = _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip=candidate,
        stable_tip=stable_tip,
        last_promoted=last_promoted,
        ancestry={(last_promoted, candidate): True, (candidate, candidate): True},
    )
    state["push_failure"] = True

    with pytest.raises(
        promote_snapshot.PromotionError,
        match="compare-and-swap stable push failed",
    ):
        promote_snapshot.promote(candidate, rollback=False)
    assert state["lease"] == f"--force-with-lease=refs/heads/stable:{stable_tip}"


def test_existing_stable_requires_recognized_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected stable ancestry stops with explicit bootstrap guidance."""
    candidate = "a" * 40
    _configure(
        monkeypatch,
        candidate=candidate,
        beta_tip=candidate,
        stable_tip="b" * 40,
        last_promoted=None,
    )

    def reject_metadata(stable_sha: str) -> str:
        assert stable_sha == "b" * 40
        raise promote_snapshot.PromotionError(
            "existing stable branch has no recognized Promoted-Beta-SHA "
            "metadata; use the documented maintainer bootstrap procedure"
        )

    monkeypatch.setattr(promote_snapshot, "_read_promoted_sha", reject_metadata)
    with pytest.raises(
        promote_snapshot.PromotionError,
        match="maintainer bootstrap procedure",
    ):
        promote_snapshot.promote(candidate, rollback=False)
