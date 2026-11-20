"""Promote an exact reviewed beta commit to the stable output branch."""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FULL_SHA = re.compile(r"^[0-9A-Fa-f]{40,64}$")
_PROMOTED_SHA = re.compile(r"(?m)^Promoted-Beta-SHA:\s*([0-9A-Fa-f]{40,64})\s*$")


class PromotionError(RuntimeError):
    """A stable promotion is unsafe or cannot be verified."""


def _run_git(
    arguments: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PromotionError(
            f"git {' '.join(arguments)} failed" + (f": {detail}" if detail else "")
        )
    return completed


def _full_sha(value: str) -> str:
    if not _FULL_SHA.fullmatch(value):
        raise PromotionError("beta_sha must be a full hexadecimal commit SHA")
    return value.lower()


def _remote_sha(branch: str) -> str | None:
    result = _run_git(
        ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
    )
    line = result.stdout.strip()
    return line.split(None, 1)[0].lower() if line else None


def _is_ancestor(ancestor_sha: str, descendant_sha: str) -> bool:
    result = _run_git(
        ["merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        check=False,
    )
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or result.stdout.strip()
        raise PromotionError(
            "could not compare Git ancestry" + (f": {detail}" if detail else "")
        )
    return result.returncode == 0


def _tree_sha(commit_sha: str) -> str:
    return _run_git(["rev-parse", f"{commit_sha}^{{tree}}"]).stdout.strip().lower()


def _commit_message(commit_sha: str) -> str:
    return _run_git(["show", "-s", "--format=%B", commit_sha]).stdout


def _read_promoted_sha(stable_sha: str) -> str:
    match = _PROMOTED_SHA.search(_commit_message(stable_sha))
    if not match:
        raise PromotionError(
            "existing stable branch has no recognized Promoted-Beta-SHA "
            "metadata; use the documented maintainer bootstrap procedure"
        )
    return _full_sha(match.group(1))


def _create_stable_commit(
    candidate_sha: str,
    stable_tip: str | None,
) -> str:
    candidate_tree = _tree_sha(candidate_sha)
    message = (
        f"release: publish beta snapshot {candidate_sha}\n\n"
        f"Promoted-Beta-SHA: {candidate_sha}\n"
        "Co-authored-by: Copilot "
        "<223556219+Copilot@users.noreply.github.com>\n"
    )
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Mapping Momentum Publisher",
            "GIT_AUTHOR_EMAIL": "223556219+Copilot@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "Mapping Momentum Publisher",
            "GIT_COMMITTER_EMAIL": "223556219+Copilot@users.noreply.github.com",
        }
    )
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "commit-tree", candidate_tree, "-p", stable_tip]
        if stable_tip
        else ["git", "-C", str(ROOT), "commit-tree", candidate_tree],
        input=message,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PromotionError(
            "could not finalize stable release commit"
            + (f": {detail}" if detail else "")
        )
    stable_sha = completed.stdout.strip()
    return _full_sha(stable_sha)


def _push_environment() -> dict[str, str]:
    """Build a push environment that does not persist a PAT in git config."""
    env = os.environ.copy()
    pat = env.get("MAPPING_MOMENTUM_PUBLISH_PAT")
    if pat:
        credential = base64.b64encode(f"x-access-token:{pat}".encode("ascii")).decode(
            "ascii"
        )
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {credential}"
    return env


def promote(beta_sha: str, *, rollback: bool) -> str:
    """Promote or roll back an exact beta snapshot to stable."""
    beta_sha = _full_sha(beta_sha)

    _run_git(["fetch", "origin", "+refs/heads/beta:refs/remotes/origin/beta"])
    _run_git(
        ["fetch", "origin", "+refs/heads/stable:refs/remotes/origin/stable"],
        check=False,
    )

    beta_tip = _remote_sha("beta")
    if beta_tip is None:
        raise PromotionError("remote beta branch does not exist")
    stable_tip = _remote_sha("stable")

    cat_file = _run_git(
        ["cat-file", "-e", f"{beta_sha}^{{commit}}"],
        check=False,
    )
    if cat_file.returncode != 0:
        raise PromotionError(f"{beta_sha} does not resolve to a local commit")
    if not _is_ancestor(beta_sha, beta_tip):
        raise PromotionError(f"{beta_sha} is not reachable from remote beta {beta_tip}")

    candidate_tree = _tree_sha(beta_sha)

    if stable_tip is None:
        stable_sha = _create_stable_commit(beta_sha, None)
    else:
        last_beta_sha = _read_promoted_sha(stable_tip)
        cat_file = _run_git(
            ["cat-file", "-e", f"{last_beta_sha}^{{commit}}"],
            check=False,
        )
        if cat_file.returncode != 0:
            raise PromotionError("stable metadata names an unknown beta commit")

        if beta_sha == last_beta_sha:
            if _tree_sha(stable_tip) != candidate_tree:
                raise PromotionError(
                    "stable metadata is idempotent but stable tree differs "
                    "from the beta candidate tree"
                )
            stable_sha = stable_tip
            print(f"Stable promotion is idempotent: {stable_sha}")
        elif _is_ancestor(last_beta_sha, beta_sha):
            stable_sha = _create_stable_commit(beta_sha, stable_tip)
        elif _is_ancestor(beta_sha, last_beta_sha):
            if not rollback:
                raise PromotionError(
                    "candidate is older than stable; set rollback=true "
                    "to explicitly permit rollback"
                )
            stable_sha = _create_stable_commit(beta_sha, stable_tip)
        else:
            raise PromotionError(
                "candidate beta commit diverges from the last promoted "
                "snapshot; rollback override cannot permit divergence"
            )

    if stable_tip is not None and stable_sha == stable_tip:
        verified_stable = _remote_sha("stable")
        if verified_stable != stable_tip:
            raise PromotionError("stable ref changed unexpectedly")
        print(f"Stable deployment SHA: {stable_sha}")
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as handle:
                handle.write(f"stable_sha={stable_sha}\n")
        return stable_sha

    if _tree_sha(stable_sha) != candidate_tree:
        raise PromotionError(
            "stable release tree is not exactly equal to the beta candidate tree"
        )

    push_env = _push_environment()
    if stable_tip is None:
        lease = "--force-with-lease=refs/heads/stable:"
    else:
        lease = f"--force-with-lease=refs/heads/stable:{stable_tip}"
    pushed = _run_git(
        [
            "push",
            "origin",
            lease,
            f"{stable_sha}:refs/heads/stable",
        ],
        check=False,
        env=push_env,
    )
    if pushed.returncode != 0:
        detail = pushed.stderr.strip() or pushed.stdout.strip()
        raise PromotionError(
            "compare-and-swap stable push failed" + (f": {detail}" if detail else "")
        )

    verified_stable = _remote_sha("stable")
    if verified_stable != stable_sha:
        raise PromotionError(
            f"stable push completed but remote verification did not match {stable_sha}"
        )

    print(f"Stable deployment SHA: {stable_sha}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"stable_sha={stable_sha}\n")
    return stable_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Promote an exact beta report snapshot to stable"
    )
    parser.add_argument(
        "--beta-sha",
        default=os.environ.get("BETA_SHA"),
        help="Full beta commit SHA",
    )
    parser.add_argument(
        "--rollback",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("ROLLBACK", "false").lower() == "true",
        help="Explicitly permit promotion of an older beta snapshot",
    )
    args = parser.parse_args(argv)
    if not args.beta_sha:
        print("error: --beta-sha or BETA_SHA is required", file=sys.stderr)
        return 2
    try:
        promote(args.beta_sha, rollback=args.rollback)
    except PromotionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
