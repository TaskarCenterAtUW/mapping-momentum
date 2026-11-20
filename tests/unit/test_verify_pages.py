"""Tests for exact GitHub Pages deployment verification."""

from __future__ import annotations

from urllib.request import Request

import pytest

from utilities import verify_pages


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if len(exc_info) != 3:
            raise AssertionError("response context received invalid exception data")
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]


def test_verify_deployment_matches_exact_stable_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live index and Golden Sample equal files from the stable SHA."""
    stable_sha = "a" * 40
    expected = {
        "index.html": "<!DOCTYPE html><html>index</html>\n",
        "golden-sample/index.html": "<!DOCTYPE html><html>golden</html>\n",
    }
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    def fake_api_json(path: str, token: str) -> dict[str, str]:
        """Return the built deployment after validating the API request."""
        assert path == "/pages/builds/latest"
        assert token == "test-token"
        return {"status": "built", "commit": stable_sha}

    def fake_git_file(sha: str, path: str) -> str:
        """Return stable content only for a requested fixture file."""
        assert sha == stable_sha
        assert path in expected
        return expected[path]

    def fake_urlopen(
        request: Request,
        data: bytes | None = None,
        timeout: float = 30,
    ) -> _Response:
        """Serve the matching fixture while checking request options."""
        assert data is None
        assert timeout == 30
        path = request.full_url.split("/", 3)[-1].removeprefix("mapping-momentum/")
        assert path in expected
        return _Response(expected[path].encode())

    monkeypatch.setattr(
        verify_pages,
        "_api_json",
        fake_api_json,
    )
    monkeypatch.setattr(verify_pages, "_git_file", fake_git_file)
    monkeypatch.setattr(
        verify_pages.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    verify_pages.verify_deployment(
        stable_sha,
        "https://example.test/mapping-momentum/",
        timeout_seconds=1,
        poll_seconds=0,
    )


def test_verify_deployment_rejects_drift_from_stable_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful Pages build is insufficient when served bytes differ."""
    stable_sha = "a" * 40
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    def fake_api_json(path: str, token: str) -> dict[str, str]:
        """Return the built deployment after validating the API request."""
        assert path == "/pages/builds/latest"
        assert token == "test-token"
        return {"status": "built", "commit": stable_sha}

    def fake_git_file(sha: str, path: str) -> str:
        """Confirm the verifier checked the stable first-page file."""
        assert sha == stable_sha
        assert path == "index.html"
        return "<!DOCTYPE html><html>expected</html>\n"

    def fake_urlopen(
        request: Request,
        data: bytes | None = None,
        timeout: float = 30,
    ) -> _Response:
        """Serve intentionally drifted content for the requested page."""
        assert data is None
        assert timeout == 30
        assert request.full_url == "https://example.test/index.html"
        return _Response(b"<!DOCTYPE html><html>different</html>\n")

    monkeypatch.setattr(
        verify_pages,
        "_api_json",
        fake_api_json,
    )
    monkeypatch.setattr(verify_pages, "_git_file", fake_git_file)
    monkeypatch.setattr(
        verify_pages.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(verify_pages.VerificationError, match="did not match"):
        verify_pages.verify_deployment(
            stable_sha,
            "https://example.test/",
            timeout_seconds=1,
            poll_seconds=0,
        )
