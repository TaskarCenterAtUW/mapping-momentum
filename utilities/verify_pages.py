"""Verify that GitHub Pages deployed an exact stable snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_FULL_SHA = re.compile(r"^[0-9A-Fa-f]{40,64}$")


class VerificationError(RuntimeError):
    """A Pages deployment could not be verified."""


def _api_json(path: str, token: str) -> dict[str, object] | list[object]:
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise VerificationError("GITHUB_REPOSITORY is required")
    url = f"https://api.github.com/repos/{repository}{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mapping-momentum-pages-verifier",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _git_file(stable_sha: str, path: str) -> str:
    """Read one expected public file from the exact stable commit."""
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "show",
            f"{stable_sha}:{path}",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerificationError(
            f"could not read {path} from stable commit {stable_sha}"
            + (f": {detail}" if detail else "")
        )
    return completed.stdout


def verify_deployment(
    stable_sha: str,
    public_url: str,
    *,
    timeout_seconds: int,
    poll_seconds: int,
) -> None:
    if not _FULL_SHA.fullmatch(stable_sha):
        raise VerificationError("stable_sha must be a full hexadecimal SHA")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise VerificationError(
            "GITHUB_TOKEN is required to verify the exact Pages deployment"
        )

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            build = _api_json("/pages/builds/latest", token)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise VerificationError(
                f"could not read latest Pages build: {exc}"
            ) from exc
        if isinstance(build, dict):
            status = build.get("status")
            commit = build.get("commit")
            if status == "built" and commit:
                if str(commit).lower() == stable_sha.lower():
                    break
                if time.monotonic() >= deadline:
                    raise VerificationError(
                        "latest Pages build did not match stable SHA "
                        f"{stable_sha}; latest commit was {commit}"
                    )
            elif status == "errored":
                raise VerificationError("GitHub Pages reported an errored build")
        if time.monotonic() >= deadline:
            raise VerificationError("timed out waiting for the GitHub Pages build")
        time.sleep(poll_seconds)

    base = public_url.rstrip("/")
    for path in ("index.html", "golden-sample/index.html"):
        url = f"{base}/{path}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "mapping-momentum-pages-smoke"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(2_000_000).decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise VerificationError(
                f"public smoke test failed for {url}: {exc}"
            ) from exc
        if "<html" not in body.lower():
            raise VerificationError(
                f"public smoke test returned no HTML document: {url}"
            )
        expected = _git_file(stable_sha, path)
        if body != expected:
            raise VerificationError(
                f"public smoke test for {url} did not match stable commit {stable_sha}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify exact GitHub Pages deployment and public URLs"
    )
    parser.add_argument(
        "--stable-sha",
        default=os.environ.get("STABLE_SHA"),
        required=False,
    )
    parser.add_argument(
        "--public-url",
        default=os.environ.get("PUBLIC_URL"),
        required=False,
    )
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if not args.stable_sha:
        print("error: --stable-sha or STABLE_SHA is required", file=sys.stderr)
        return 2
    if not args.public_url:
        print("error: --public-url or PUBLIC_URL is required", file=sys.stderr)
        return 2
    try:
        verify_deployment(
            args.stable_sha,
            args.public_url,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except VerificationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Verified GitHub Pages build and public smoke test for {args.stable_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
