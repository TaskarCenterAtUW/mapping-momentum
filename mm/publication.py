"""Prepare and approve local report publication snapshots."""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeGuard, cast

from mm.common.io import read_json, require_safe_path_component, write_json, write_text
from mm.config.loader import ConfigError, load_event_config

_FULL_SHA = re.compile(r"^[0-9A-Fa-f]{40,64}$")
_EVENT_SERIES_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<series>[a-z0-9]+)(?:-|$)")
PRIVACY_AFFIRMATION = (
    "Yes, I checked these and confirmed there is nothing that needs "
    "redaction or anonymization."
)


class PublicationError(RuntimeError):
    """A publication operation could not be completed safely."""


@dataclass(frozen=True)
class PreparedPublication:
    """Details for one locally prepared beta snapshot."""

    sha: str
    staging_directory: Path | None
    beta_parent_sha: str | None
    commit_created: bool


def project_version(repo_root: Path) -> str:
    """Read and validate the project version from pyproject.toml."""
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise PublicationError("pyproject.toml must define a non-empty project version")
    return version.strip()


def default_anonymized_root(repo_root: Path) -> Path:
    """Return the default local anonymized report root for this source version."""
    version_root = repo_root / "local-output" / f"v{project_version(repo_root)}"
    return version_root / "anonymized"


def run_git(
    repo_root: Path,
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run git with a repository-local working directory."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PublicationError(
            f"git {' '.join(arguments)} failed" + (f": {detail}" if detail else "")
        )
    return completed


def full_sha(value: object) -> str:
    """Require a full hexadecimal Git commit ID."""
    if not isinstance(value, str) or not _FULL_SHA.fullmatch(value):
        raise PublicationError("expected a full hexadecimal Git commit SHA")
    return value.lower()


def _is_json_object(value: object) -> TypeGuard[dict[str, Any]]:
    """Narrow decoded JSON to an object with string keys."""
    if not isinstance(value, dict):
        return False
    object_items = cast(dict[object, object], value)
    return all(isinstance(key, str) for key in object_items)


def _event_series(event_id: str) -> str | None:
    match = _EVENT_SERIES_PATTERN.match(event_id)
    return match.group("series") if match else None


def publication_allowlist(
    repo_root: Path,
    anonymized_root: Path,
) -> tuple[list[tuple[Path, str]], list[str]]:
    """Discover configured anonymized HTML inputs and expected snapshot paths."""
    config_root = repo_root / "configs" / "events"
    configs: list[dict[str, Any]] = []
    ids_to_paths: dict[str, Path] = {}

    for config_path in sorted(config_root.rglob("event.json")):
        relative_parts = config_path.relative_to(config_root).parts[:-1]
        if any(part.casefold() == "template" for part in relative_parts):
            continue
        try:
            config = load_event_config(config_path)
        except (ConfigError, OSError) as exc:
            raise PublicationError(f"could not load {config_path}: {exc}") from exc
        if config.get("publish", True) is False:
            continue
        event_id = config["id"]
        if event_id in ids_to_paths:
            raise PublicationError(
                f"duplicate event id {event_id!r} in "
                f"{ids_to_paths[event_id]} and {config_path}"
            )
        ids_to_paths[event_id] = config_path
        configs.append(config)

    if not configs:
        raise PublicationError(f"no event.json configs found under {config_root}")

    discovered: list[tuple[Path, str]] = []
    event_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for config in configs:
        event_id = require_safe_path_component(config["id"], "event id")
        for activity in config["activities"]:
            activity_id = require_safe_path_component(activity["id"], "activity id")
            relative = f"events/{event_id}/{activity_id}/index.html"
            source = anonymized_root / relative
            discovered.append((source, relative))
            event_records.append((config, activity))

    series_entries: dict[str, int] = {}
    for config in configs:
        series = _event_series(config["id"])
        if series:
            series_entries[series] = series_entries.get(series, 0) + 1

    aggregate_records: list[tuple[str, str]] = []
    for series, count in sorted(series_entries.items()):
        if count < 2:
            continue
        series = require_safe_path_component(series, "aggregate series")
        relative = f"events/aggregates/{series}/index.html"
        source = anonymized_root / relative
        discovered.append((source, relative))
        aggregate_records.append((series, relative))

    expected_paths = [relative for _, relative in discovered]
    expected_paths.extend(["index.html", "golden-sample/index.html", ".nojekyll"])
    return discovered, expected_paths


def _publication_index(
    repo_root: Path,
) -> str:
    """Generate the public index from configured real report destinations."""
    config_root = repo_root / "configs" / "events"
    event_links: list[tuple[str, str, str]] = []
    aggregate_links: list[tuple[str, str]] = []

    for config_path in sorted(config_root.rglob("event.json")):
        relative_parts = config_path.relative_to(config_root).parts[:-1]
        if any(part.casefold() == "template" for part in relative_parts):
            continue
        config = load_event_config(config_path)
        if config.get("publish", True) is False:
            continue
        event_id = config["id"]
        event_name = str(config.get("name") or event_id)
        for activity in config["activities"]:
            activity_id = activity["id"]
            activity_name = str(activity.get("label") or activity_id)
            relative = f"events/{event_id}/{activity_id}/index.html"
            event_links.append((relative, event_name, activity_name))

    series_entries: dict[str, int] = {}
    for config_path in sorted(config_root.rglob("event.json")):
        relative_parts = config_path.relative_to(config_root).parts[:-1]
        if any(part.casefold() == "template" for part in relative_parts):
            continue
        config = load_event_config(config_path)
        if config.get("publish", True) is False:
            continue
        series = _event_series(config["id"])
        if series:
            series_entries[series] = series_entries.get(series, 0) + 1
    for series, count in sorted(series_entries.items()):
        if count >= 2:
            aggregate_links.append(
                (f"events/aggregates/{series}/index.html", series.upper())
            )

    event_items = "\n".join(
        "        "
        f'<li><a href="{html.escape(relative, quote=True)}">'
        f"{html.escape(event_name)}"
        f"{' — ' + html.escape(activity_name) if activity_name else ''}"
        "</a></li>"
        for relative, event_name, activity_name in event_links
    )
    aggregate_items = "\n".join(
        "        "
        f'<li><a href="{html.escape(relative, quote=True)}">'
        f"{html.escape(title)} aggregate"
        "</a></li>"
        for relative, title in aggregate_links
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "  <title>Mapping Momentum Reports</title>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>Mapping Momentum Reports</h1>\n"
        "    <h2>Event reports</h2>\n"
        "    <ul>\n"
        f"{event_items}\n"
        "    </ul>\n"
        "    <h2>Aggregate reports</h2>\n"
        "    <ul>\n"
        f"{aggregate_items}\n"
        "    </ul>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _generate_golden_sample(repo_root: Path, staging_dir: Path) -> None:
    """Generate the deterministic anonymized maximal sample into staging."""
    from example.run_offline import run_offline

    golden_output = staging_dir / ".golden-output"
    _, report_path = run_offline(
        repo_root / "example" / "maximal",
        golden_output,
        anonymize=True,
    )
    destination = staging_dir / "golden-sample" / "index.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report_path, destination)
    shutil.rmtree(golden_output)


def _safe_staging_copy(
    source: Path,
    staging_dir: Path,
    relative: str,
) -> None:
    """Copy one allowlisted HTML file without following symlinks."""
    if source.is_symlink():
        raise PublicationError(f"publication input is a symlink: {source}")
    if not source.is_file():
        raise PublicationError(f"missing publication input: {source}")

    destination = staging_dir / Path(relative)
    resolved_destination = destination.resolve()
    resolved_staging = staging_dir.resolve()
    try:
        resolved_destination.relative_to(resolved_staging)
    except ValueError as exc:
        raise PublicationError(
            f"publication destination escapes staging: {relative}"
        ) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _validate_staging_allowlist(
    staging_dir: Path,
    expected_allowlist: set[str],
) -> None:
    """Reject missing, unexpected, symlink, and non-file staged entries."""
    entries = list(staging_dir.rglob("*"))
    symlinks = [
        path.relative_to(staging_dir).as_posix()
        for path in entries
        if path.is_symlink()
    ]
    if symlinks:
        raise PublicationError(
            "publication staging contains symlinks: " + ", ".join(sorted(symlinks))
        )
    non_files = [
        path.relative_to(staging_dir).as_posix()
        for path in entries
        if path.exists() and not path.is_dir() and not path.is_file()
    ]
    if non_files:
        raise PublicationError(
            "publication staging contains unsupported entries: "
            + ", ".join(sorted(non_files))
        )
    staged_files = {
        path.relative_to(staging_dir).as_posix() for path in entries if path.is_file()
    }
    if staged_files != expected_allowlist:
        missing = sorted(expected_allowlist - staged_files)
        unexpected = sorted(staged_files - expected_allowlist)
        raise PublicationError(
            "publication staging allowlist mismatch"
            + (f"; missing: {', '.join(missing)}" if missing else "")
            + (f"; unexpected: {', '.join(unexpected)}" if unexpected else "")
        )


def _remove_worktree_contents(worktree: Path) -> None:
    """Remove a worktree's entire tracked and untracked tree, not the worktree."""
    for child in worktree.iterdir():
        if child.name == ".git":
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)


def _remote_sha(repo_root: Path, branch: str) -> str | None:
    """Read a remote branch SHA without guessing on a missing ref."""
    result = run_git(
        repo_root,
        ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
        check=True,
    )
    line = result.stdout.strip()
    if not line:
        return None
    return line.split(None, 1)[0]


def _is_ancestor(
    repo_root: Path,
    ancestor_sha: str,
    descendant_sha: str,
) -> bool:
    result = run_git(
        repo_root,
        ["merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        check=False,
    )
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or result.stdout.strip()
        raise PublicationError(
            "could not compare Git ancestry" + (f": {detail}" if detail else "")
        )
    return result.returncode == 0


def prepare_publication(
    repo_root: Path,
    anonymized_root: Path,
    *,
    remote_name: str = "origin",
) -> PreparedPublication:
    """Build and commit an allowlisted public snapshot against remote beta."""
    repo_root = repo_root.resolve()
    anonymized_root = anonymized_root.resolve()

    if remote_name != "origin":
        raise PublicationError("publication preparation requires the 'origin' remote")

    discovered, expected_paths = publication_allowlist(
        repo_root,
        anonymized_root,
    )

    local_storage = repo_root / "local-storage"
    local_storage.mkdir(parents=True, exist_ok=True)
    candidate_directory: Path | None = None

    with tempfile.TemporaryDirectory(
        prefix="mapping-momentum-publish-",
        dir=local_storage,
    ) as temp_name:
        temp_root = Path(temp_name)
        staging_dir = temp_root / "staging"
        staging_dir.mkdir()

        for source, relative in discovered:
            _safe_staging_copy(source, staging_dir, relative)

        _generate_golden_sample(repo_root, staging_dir)
        write_text(
            staging_dir / "index.html",
            _publication_index(repo_root),
        )
        write_text(staging_dir / ".nojekyll", "")

        _validate_staging_allowlist(staging_dir, set(expected_paths))

        remote_beta = _remote_sha(repo_root, "beta")
        worktree = temp_root / "beta-worktree"
        beta_parent_sha: str | None = None
        worktree_added = False
        try:
            if remote_beta:
                run_git(
                    repo_root,
                    ["fetch", "origin", "+refs/heads/beta:refs/remotes/origin/beta"],
                )
                beta_parent_sha = (
                    run_git(
                        repo_root,
                        ["rev-parse", "refs/remotes/origin/beta"],
                    )
                    .stdout.strip()
                    .lower()
                )
                run_git(
                    repo_root,
                    ["worktree", "add", "--detach", str(worktree), "origin/beta"],
                )
                worktree_added = True
            else:
                run_git(
                    repo_root,
                    ["worktree", "add", "--detach", str(worktree), "HEAD"],
                )
                worktree_added = True
                run_git(
                    worktree,
                    ["switch", "--orphan", "beta-candidate"],
                    check=True,
                )

            _remove_worktree_contents(worktree)
            for staged in staging_dir.rglob("*"):
                if staged.is_symlink():
                    raise PublicationError(f"refusing staged symlink: {staged}")
                if not staged.is_file():
                    continue
                relative = staged.relative_to(staging_dir)
                destination = worktree / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staged, destination)

            run_git(worktree, ["add", "-A"])
            diff = run_git(
                worktree,
                ["diff", "--cached", "--quiet"],
                check=False,
            )
            commit_created = diff.returncode == 1
            if commit_created:
                run_git(
                    worktree,
                    [
                        "-c",
                        "user.name=Mapping Momentum Publisher",
                        "-c",
                        "user.email=223556219+Copilot@users.noreply.github.com",
                        "commit",
                        "-m",
                        "publish: update report snapshot",
                        "-m",
                        "Co-authored-by: Copilot "
                        "<223556219+Copilot@users.noreply.github.com>",
                    ],
                )

            sha = run_git(worktree, ["rev-parse", "HEAD"]).stdout.strip()
            sha = full_sha(sha)
            run_git(
                repo_root,
                ["update-ref", "refs/heads/beta-candidate", sha],
            )

            candidate_directory = local_storage / "publication-candidates" / sha
            candidate_directory.mkdir(parents=True, exist_ok=True)
            write_json(
                candidate_directory / "candidate.json",
                {
                    "sha": sha,
                    "beta_parent_sha": beta_parent_sha,
                    "commit_created": commit_created,
                    "prepared_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        finally:
            if worktree_added:
                run_git(
                    repo_root,
                    ["worktree", "remove", "--force", str(worktree)],
                    check=False,
                )

    return PreparedPublication(
        sha=sha,
        staging_directory=candidate_directory,
        beta_parent_sha=beta_parent_sha,
        commit_created=commit_created,
    )


def candidate_check_path(repo_root: Path, sha: str) -> Path:
    """Return the local report-check result path for an exact SHA."""
    sha = full_sha(sha)
    return repo_root / "local-storage" / "report-checks" / sha / "result.json"


def read_successful_check(repo_root: Path, sha: str) -> dict[str, Any]:
    """Read a report-check result and require success for the exact SHA."""
    sha = full_sha(sha)
    path = candidate_check_path(repo_root, sha)
    if not path.is_file():
        raise PublicationError(f"no report check result found for {sha}: {path}")
    try:
        result_value: object = read_json(path)
    except (OSError, ValueError) as exc:
        raise PublicationError(
            f"could not read report check result {path}: {exc}"
        ) from exc
    if not _is_json_object(result_value):
        raise PublicationError(f"report check result must be a JSON object: {path}")
    result = result_value
    if result.get("sha") != sha:
        raise PublicationError(
            f"report check result was bound to {result.get('sha')!r}, not {sha}"
        )
    if result.get("success") is not True:
        raise PublicationError(f"report checks did not succeed for {sha}")
    return result


def approve_and_push_publication(
    repo_root: Path,
    sha: str,
    *,
    affirmation: str,
    remote_name: str = "origin",
) -> str:
    """Require exact-SHA checks and an explicit approval before beta push."""
    repo_root = repo_root.resolve()
    sha = full_sha(sha)
    if affirmation != PRIVACY_AFFIRMATION:
        raise PublicationError(
            "publication approval requires the exact privacy affirmation; "
            "no beta push was made"
        )
    if remote_name != "origin":
        raise PublicationError("publication approval requires the 'origin' remote")

    read_successful_check(repo_root, sha)
    cat_file = run_git(
        repo_root,
        ["cat-file", "-e", f"{sha}^{{commit}}"],
        check=False,
    )
    if cat_file.returncode != 0:
        raise PublicationError(f"{sha} does not resolve to a local commit")

    candidate_ref = run_git(
        repo_root,
        ["rev-parse", "--verify", "refs/heads/beta-candidate"],
        check=False,
    )
    if candidate_ref.returncode != 0:
        raise PublicationError("the local beta-candidate ref is missing; prepare again")
    candidate_sha = candidate_ref.stdout.strip().lower()
    if candidate_sha != sha:
        raise PublicationError(
            f"approval SHA {sha} is not the current beta candidate {candidate_sha}"
        )

    candidate_path = (
        repo_root / "local-storage" / "publication-candidates" / sha / "candidate.json"
    )
    try:
        candidate_value: object = read_json(candidate_path)
    except (OSError, ValueError) as exc:
        raise PublicationError(
            f"could not read candidate metadata {candidate_path}: {exc}"
        ) from exc
    if not _is_json_object(candidate_value) or candidate_value.get("sha") != sha:
        raise PublicationError(f"candidate metadata is not bound to reviewed SHA {sha}")
    candidate = candidate_value
    beta_parent_sha: object = candidate.get("beta_parent_sha")
    if beta_parent_sha is not None:
        beta_parent_sha = full_sha(beta_parent_sha)

    fetch = run_git(
        repo_root,
        ["fetch", "origin", "+refs/heads/beta:refs/remotes/origin/beta"],
        check=False,
    )
    remote_beta = _remote_sha(repo_root, "beta")
    if remote_beta is None:
        if fetch.returncode != 0 and "couldn't find remote ref beta" not in (
            fetch.stderr
        ):
            detail = fetch.stderr.strip() or fetch.stdout.strip()
            raise PublicationError(
                "could not fetch remote beta" + (f": {detail}" if detail else "")
            )
        if beta_parent_sha is not None:
            raise PublicationError(
                "remote beta branch disappeared during approval; prepare again"
            )
    else:
        remote_beta = remote_beta.lower()
        if beta_parent_sha is None:
            raise PublicationError(
                "remote beta appeared after preparation; reprepare before pushing"
            )
        if remote_beta != beta_parent_sha:
            if not _is_ancestor(repo_root, remote_beta, sha):
                raise PublicationError(
                    "remote beta has advanced since preparation; "
                    "reprepare before pushing"
                )
        elif not _is_ancestor(repo_root, beta_parent_sha, sha):
            raise PublicationError(
                "beta candidate is not based on the reviewed beta parent"
            )

    run_git(
        repo_root,
        ["push", "origin", f"{sha}:refs/heads/beta"],
    )
    verified_remote = _remote_sha(repo_root, "beta")
    if verified_remote is None or verified_remote.lower() != sha:
        raise PublicationError(
            "beta push completed but remote verification did not match "
            f"the reviewed SHA {sha}"
        )

    record_directory = repo_root / "local-storage" / "published"
    record_directory.mkdir(parents=True, exist_ok=True)
    record_path = record_directory / f"{sha}.json"
    write_json(
        record_path,
        {
            "sha": sha,
            "remote": remote_name,
            "branch": "beta",
            "pushed_at": datetime.now(timezone.utc).isoformat(),
            "privacy_review_confirmed": True,
        },
    )
    return sha
