"""Prepare the development environment and local publication checks."""

from __future__ import annotations

import base64
import hashlib
import io
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_AXE_CORE_VERSION = "4.14.0"
_ARCHIVE_URL = "https://registry.npmjs.org/axe-core/-/axe-core-4.14.0.tgz"
_ARCHIVE_INTEGRITY = (
    "sha512-9WTZxEjsZ7b13TH8JPmbV2z8CHbl80/2hm3XPEG4JgNdQLK81IBRXmSxHfMAOkSq"
    "QeRxT/0dwNDz2GOm3zzpcQ=="
)
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
_PACKAGE_FILES = (
    ("package/axe.min.js", "axe.min.js"),
    ("package/LICENSE", "LICENSE.axe-core"),
)


class SetupError(RuntimeError):
    """The local axe-core setup could not be completed safely."""


def _run_command(
    command: tuple[str, ...],
    repo_root: Path,
    description: str,
) -> None:
    """Run a setup command and report actionable failures."""
    try:
        subprocess.run(command, cwd=repo_root, check=True)
    except FileNotFoundError as exc:
        raise SetupError(
            f"could not run {description}: {command[0]} was not found on PATH"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SetupError(
            f"{description} failed with exit code {exc.returncode}"
        ) from exc
    except OSError as exc:
        raise SetupError(f"could not start {description}: {exc}") from exc


def setup_environment(repo_root: Path) -> None:
    """Sync locked development dependencies and install Playwright Chromium."""
    root = repo_root.resolve()
    _run_command(
        ("uv", "sync", "--locked", "--group", "dev"),
        root,
        "syncing the locked development environment",
    )
    _run_command(
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
        "installing Playwright Chromium",
    )


def _download_archive() -> bytes:
    """Download the pinned axe-core archive from the npm registry."""
    request = urllib.request.Request(
        _ARCHIVE_URL,
        headers={"User-Agent": "mapping-momentum-initial-setup"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            archive = response.read(_MAX_ARCHIVE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SetupError(f"could not download axe-core: {exc}") from exc

    if len(archive) > _MAX_ARCHIVE_BYTES:
        raise SetupError("axe-core package archive exceeds the size limit")
    return archive


def _read_package_files(archive: bytes) -> dict[str, bytes]:
    """Verify the archive and read only the asset and its license."""
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(archive).digest()).decode(
        "ascii"
    )
    if integrity != _ARCHIVE_INTEGRITY:
        raise SetupError(f"axe-core {_AXE_CORE_VERSION} archive integrity check failed")

    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            files: dict[str, bytes] = {}
            for package_path, local_name in _PACKAGE_FILES:
                try:
                    member = package.getmember(package_path)
                except KeyError as exc:
                    raise SetupError(
                        f"axe-core archive is missing {package_path}"
                    ) from exc
                if not member.isfile():
                    raise SetupError(
                        f"axe-core archive entry is not a file: {package_path}"
                    )
                source = package.extractfile(member)
                if source is None:
                    raise SetupError(
                        f"could not read axe-core archive entry: {package_path}"
                    )
                content = source.read()
                if len(content) != member.size:
                    raise SetupError(
                        f"axe-core archive entry is truncated: {package_path}"
                    )
                files[local_name] = content
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise SetupError(f"could not read axe-core package archive: {exc}") from exc

    license_text = files["LICENSE.axe-core"]
    if b"Mozilla Public License, version 2.0" not in license_text:
        raise SetupError("axe-core archive has an unrecognized license")
    return files


def _install_files(vendor_dir: Path, files: dict[str, bytes]) -> None:
    """Install verified files without overwriting different local content."""
    try:
        if vendor_dir.parent.is_symlink() or vendor_dir.is_symlink():
            raise SetupError(
                f"refusing to install axe-core through a symlink: {vendor_dir}"
            )
        vendor_dir.mkdir(parents=True, exist_ok=True)
        destinations = {vendor_dir / name: content for name, content in files.items()}
        for path, content in destinations.items():
            if path.is_symlink():
                raise SetupError(
                    f"refusing to install axe-core through a symlink: {path}"
                )
            if path.exists() and (not path.is_file() or path.read_bytes() != content):
                raise SetupError(f"refusing to overwrite different local file: {path}")
        for path, content in destinations.items():
            if not path.exists():
                path.write_bytes(content)
    except OSError as exc:
        raise SetupError(f"could not install axe-core files: {exc}") from exc


def setup_axe_core(repo_root: Path) -> tuple[Path, Path]:
    """Install axe-core and its license under ``tests/vendor``."""
    archive = _download_archive()
    files = _read_package_files(archive)
    vendor_dir = repo_root.resolve() / "tests" / "vendor"
    _install_files(vendor_dir, files)
    return vendor_dir / "axe.min.js", vendor_dir / "LICENSE.axe-core"


def main() -> int:
    """Set up development dependencies and local publication checks."""
    try:
        setup_environment(_ROOT)
        asset_path, license_path = setup_axe_core(_ROOT)
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Development dependencies and Playwright Chromium are ready.")
    print(f"Installed axe-core {_AXE_CORE_VERSION}: {asset_path}")
    print(f"License: {license_path}")
    print("The local report check will find the axe-core asset automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
