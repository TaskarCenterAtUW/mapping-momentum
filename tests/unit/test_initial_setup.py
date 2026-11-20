"""Tests for preparing the local axe-core test asset."""

from __future__ import annotations

import base64
import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

import utilities.initial_setup as initial_setup


def _archive(files: dict[str, bytes]) -> bytes:
    """Build a small npm-style archive for setup tests."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as package:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            package.addfile(member, io.BytesIO(content))
    return output.getvalue()


def _integrity(archive: bytes) -> str:
    """Return the npm-style SHA-512 integrity for an archive."""
    digest = base64.b64encode(hashlib.sha512(archive).digest()).decode("ascii")
    return f"sha512-{digest}"


def _mock_archive(
    monkeypatch: pytest.MonkeyPatch,
    archive: bytes,
) -> None:
    """Configure setup to use a deterministic test archive."""
    monkeypatch.setattr(initial_setup, "_download_archive", lambda: archive)
    monkeypatch.setattr(
        initial_setup,
        "_ARCHIVE_INTEGRITY",
        _integrity(archive),
    )


def test_setup_environment_syncs_dependencies_then_installs_chromium(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run locked dependency sync before installing the Playwright browser."""
    calls: list[tuple[tuple[str, ...], Path, bool]] = []

    def record_command(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
    ) -> None:
        calls.append((command, cwd, check))

    monkeypatch.setattr(initial_setup.subprocess, "run", record_command)

    initial_setup.setup_environment(tmp_path)

    root = tmp_path.resolve()
    assert calls == [
        (("uv", "sync", "--locked", "--group", "dev"), root, True),
        (
            (
                "uv",
                "run",
                "--locked",
                "python",
                "-m",
                "playwright",
                "install",
                "chromium",
            ),
            root,
            True,
        ),
    ]


def test_setup_environment_stops_if_dependency_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not install Chromium if the locked environment sync fails."""
    calls: list[tuple[str, ...]] = []

    def fail_command(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
    ) -> None:
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(initial_setup.subprocess, "run", fail_command)

    with pytest.raises(
        initial_setup.SetupError,
        match="syncing the locked development environment failed",
    ):
        initial_setup.setup_environment(tmp_path)

    assert calls == [("uv", "sync", "--locked", "--group", "dev")]


def test_setup_environment_reports_missing_uv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explain that uv must be on PATH when setup cannot start."""

    def missing_command(
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
    ) -> None:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(initial_setup.subprocess, "run", missing_command)

    with pytest.raises(initial_setup.SetupError, match="uv was not found on PATH"):
        initial_setup.setup_environment(tmp_path)


def test_setup_installs_pinned_asset_and_license_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install the expected files and allow an identical repeat setup."""
    archive = _archive(
        {
            "package/axe.min.js": b"axe-core test asset",
            "package/LICENSE": b"Mozilla Public License, version 2.0\n",
        }
    )
    _mock_archive(monkeypatch, archive)

    asset_path, license_path = initial_setup.setup_axe_core(tmp_path)

    assert asset_path.read_bytes() == b"axe-core test asset"
    assert license_path.read_bytes() == (b"Mozilla Public License, version 2.0\n")
    assert initial_setup.setup_axe_core(tmp_path) == (asset_path, license_path)


def test_setup_rejects_archive_with_wrong_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not install files when the downloaded package fails its pin."""
    monkeypatch.setattr(initial_setup, "_download_archive", lambda: b"tampered")

    with pytest.raises(initial_setup.SetupError, match="integrity check failed"):
        initial_setup.setup_axe_core(tmp_path)

    assert not (tmp_path / "tests" / "vendor").exists()


def test_setup_does_not_overwrite_a_different_local_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve any existing asset that does not match the pinned archive."""
    archive = _archive(
        {
            "package/axe.min.js": b"axe-core test asset",
            "package/LICENSE": b"Mozilla Public License, version 2.0\n",
        }
    )
    _mock_archive(monkeypatch, archive)
    vendor_dir = tmp_path / "tests" / "vendor"
    vendor_dir.mkdir(parents=True)
    asset_path = vendor_dir / "axe.min.js"
    asset_path.write_bytes(b"local custom asset")

    with pytest.raises(initial_setup.SetupError, match="refusing to overwrite"):
        initial_setup.setup_axe_core(tmp_path)

    assert asset_path.read_bytes() == b"local custom asset"
    assert not (vendor_dir / "LICENSE.axe-core").exists()


@pytest.mark.parametrize("symlink_level", ["tests", "vendor", "asset"])
def test_setup_refuses_symlinked_install_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symlink_level: str,
) -> None:
    """Do not write verified assets through a symlink outside the repository."""
    archive = _archive(
        {
            "package/axe.min.js": b"axe-core test asset",
            "package/LICENSE": b"Mozilla Public License, version 2.0\n",
        }
    )
    _mock_archive(monkeypatch, archive)

    tests_dir = tmp_path / "tests"
    vendor_dir = tests_dir / "vendor"
    symlink_path = {
        "tests": tests_dir,
        "vendor": vendor_dir,
        "asset": vendor_dir / "axe.min.js",
    }[symlink_level]
    original_is_symlink = initial_setup.Path.is_symlink

    def report_symlink(path: Path) -> bool:
        return path == symlink_path or original_is_symlink(path)

    monkeypatch.setattr(initial_setup.Path, "is_symlink", report_symlink)

    with pytest.raises(initial_setup.SetupError, match="through a symlink"):
        initial_setup.setup_axe_core(tmp_path)

    assert not (vendor_dir / "axe.min.js").exists()
