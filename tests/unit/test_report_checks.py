"""Unit coverage for publication report-contract reconciliation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import mm.report_checks as report_checks
from mm.publication import PublicationError

_SHA = "a" * 40
_EVENT_ID = "2026-01-01-sample"
_EVENT_REPORT = f"events/{_EVENT_ID}/walkabout/index.html"
_GOLDEN_REPORT = "golden-sample/index.html"


class _FakeDownload:
    def save_as(self, path: str) -> None:
        Path(path).write_text(
            "<!DOCTYPE html><html><head><title>Report</title></head></html>",
            encoding="utf-8",
        )


class _FakeDownloadInfo:
    def __init__(self) -> None:
        self.value = _FakeDownload()

    def __enter__(self) -> _FakeDownloadInfo:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if len(exc_info) != 3:
            raise AssertionError("download context received invalid exception data")
        return False


class _FakeExportButton:
    def press(self, key: str) -> None:
        assert key == "Enter"


class _FakePage:
    def __init__(self, browser: _FakeBrowser, *, fresh: bool) -> None:
        self._browser = browser
        self._fresh = fresh
        self._contract: dict[str, Any] = {}

    def goto(self, url: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        if self._fresh:
            if self._browser.current_contract is None:
                raise AssertionError("fresh page has no source report contract")
            self._contract = self._browser.current_contract
            return

        relative = next(
            (path for path in self._browser.contracts if path in url),
            None,
        )
        if relative is None:
            raise AssertionError(f"unrecognized report URL: {url}")
        self._contract = self._browser.contracts[relative]
        self._browser.current_contract = self._contract

    def wait_for_timeout(self, milliseconds: int) -> None:
        assert milliseconds == 500

    def evaluate(self, expression: str) -> Any:
        if "axe.run" in expression:
            return {"violations": []}
        if self._fresh:
            return {
                "title": self._contract["title"],
                "h1Count": 1,
                "exportPresent": True,
                "resourceUrls": [],
            }
        return self._contract

    def query_selector(self, selector: str) -> _FakeExportButton | None:
        if selector == "[data-export-report]":
            return _FakeExportButton()
        return None

    def add_script_tag(self, *, path: str) -> None:
        assert Path(path).is_file()

    def expect_download(self, *, timeout: int) -> _FakeDownloadInfo:
        assert timeout == 30000
        return _FakeDownloadInfo()

    def screenshot(self, *, path: str, full_page: bool) -> None:
        assert full_page
        from PIL import Image

        Image.new("RGB", (1, 1), "white").save(path, format="PNG")

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self, contracts: dict[str, dict[str, Any]]) -> None:
        self.contracts = contracts
        self.current_contract: dict[str, Any] | None = None

    def new_page(
        self,
        *,
        viewport: dict[str, int] | None = None,
    ) -> _FakePage:
        if viewport is not None:
            assert viewport == {"width": 1440, "height": 1000}
        return _FakePage(self, fresh=viewport is None)

    def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self, contracts: dict[str, dict[str, Any]]) -> None:
        self._contracts = contracts

    def launch(self, *, headless: bool) -> _FakeBrowser:
        assert headless
        return _FakeBrowser(self._contracts)


class _FakePlaywright:
    def __init__(self, contracts: dict[str, dict[str, Any]]) -> None:
        self.chromium = _FakeChromium(contracts)


class _FakePlaywrightManager:
    def __init__(self, contracts: dict[str, dict[str, Any]]) -> None:
        self._contracts = contracts

    def __enter__(self) -> _FakePlaywright:
        return _FakePlaywright(self._contracts)

    def __exit__(self, *exc_info: object) -> bool:
        if len(exc_info) != 3:
            raise AssertionError("Playwright context received invalid exception data")
        return False


def _activity_stats() -> dict[str, Any]:
    return {
        "changeset_count": 2,
        "note_count": 1,
        "questions_answered": [{"total": 3}],
        "contributors_breakdown": [{"count": 4}, {"count": 2}],
        "features_created": [{"feature_type": "node", "count": 2}],
        "quest_type_breakdown": [{"category": "Surface", "count": 3}],
    }


def _activity_contract() -> dict[str, Any]:
    return {
        "lang": "en",
        "h1Count": 1,
        "title": "Sample Report",
        "footer": "Mapping Momentum v1.0.0",
        "exportPresent": True,
        "exportFilename": "sample-report.html",
        "summary": {
            "Changesets": "2",
            "Questions answered": "3",
            "Contributors": "2",
            "Notes": "1",
            "New map features": "2",
        },
        "cards": {
            "qt-heading": {"count": "3", "rowCounts": ["3"]},
            "fc-heading": {"count": "2", "rowCounts": ["2"]},
            "cb-heading": {"count": "2", "rowCounts": ["4", "2"]},
        },
        "questionTotal": "3",
        "eventTotals": [],
        "contributorTotals": [],
        "resourceUrls": [],
    }


def _golden_stats() -> dict[str, Any]:
    return {
        "changeset_count": 3,
        "contributor_count": 3,
        "elements_edited": 3,
        "features_created": [
            {"feature_type": "node", "count": 1},
            {"feature_type": "way", "count": 1},
        ],
        "node_count": 2,
        "note_count": 2,
        "questions_answered": [],
        "contributors_breakdown": [
            {"count": 1},
            {"count": 1},
            {"count": 1},
        ],
        "quest_type_breakdown": [
            {"category": "Synthetic Surfaces", "count": 2, "photo_count": 2},
            {"category": "Synthetic Crossings", "count": 1, "photo_count": 0},
        ],
        "relation_count": 0,
        "way_count": 1,
    }


def _golden_contract() -> dict[str, Any]:
    return {
        "lang": "en",
        "h1Count": 1,
        "title": "Golden Sample",
        "footer": "Mapping Momentum v1.0.0",
        "exportPresent": True,
        "exportFilename": "golden-sample.html",
        "summary": {
            "Changesets": "3",
            "Questions answered": "0",
            "Contributors": "3",
            "Notes": "2",
            "New map features": "2",
        },
        "cards": {
            "qt-heading": {"count": "3", "rowCounts": ["2", "1"]},
            "fc-heading": {"count": "2", "rowCounts": ["1", "1"]},
            "cb-heading": {
                "count": "3",
                "rowCounts": ["1", "1", "1"],
            },
        },
        "questionTotal": "0",
        "eventTotals": [],
        "contributorTotals": [],
        "resourceUrls": [],
    }


def _aggregate_contract() -> dict[str, Any]:
    return {
        "lang": "en",
        "h1Count": 1,
        "title": "Aggregate Report",
        "footer": "Mapping Momentum v1.0.0",
        "exportPresent": True,
        "exportFilename": "sample-aggregate.html",
        "summary": {
            "Contributors": "2",
            "Quest answers": "5",
            "Notes": "3",
            "New map features": "4",
            "Events": "2",
        },
        "eventTotals": ["3", "5"],
        "contributorTotals": ["4", "3"],
        "resourceUrls": [],
    }


def _report_html(stats: dict[str, Any]) -> str:
    serialized = json.dumps(stats, ensure_ascii=False, separators=(",", ":"))
    serialized = (
        serialized.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        '<!DOCTYPE html><html lang="en"><head><title>Report</title></head>'
        f"<body><script>const STATS = {serialized};</script></body></html>"
    )


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch,
    contracts: dict[str, dict[str, Any]],
) -> None:
    playwright_package = ModuleType("playwright")
    playwright_sync_api = ModuleType("playwright.sync_api")

    def sync_playwright() -> _FakePlaywrightManager:
        return _FakePlaywrightManager(contracts)

    setattr(playwright_package, "__path__", [])
    setattr(playwright_package, "sync_api", playwright_sync_api)
    setattr(playwright_sync_api, "sync_playwright", sync_playwright)
    monkeypatch.setitem(sys.modules, "playwright", playwright_package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", playwright_sync_api)


def _configure_checker(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    event_stats: dict[str, Any],
    event_contract: dict[str, Any],
    golden_stats: dict[str, Any] | None = None,
    golden_contract: dict[str, Any] | None = None,
) -> None:
    golden_stats = _golden_stats() if golden_stats is None else golden_stats
    golden_contract = _golden_contract() if golden_contract is None else golden_contract
    config_path = repo_root / "configs" / "events" / _EVENT_ID / "event.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "type": "event",
                "id": _EVENT_ID,
                "name": "Sample",
                "date": "2026-01-01",
                "activities": [
                    {
                        "id": "walkabout",
                        "type": "workspace",
                        "label": "Walkabout",
                        "project_group_id": ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                        "workspace_id": 1,
                        "environment": "prod",
                        "quest_definition_url": ("https://example.com/quest.json"),
                        "time_window": {
                            "start": "2026-01-01T10:00:00Z",
                            "end": "2026-01-01T12:00:00Z",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    axe_asset = repo_root / "tests" / "vendor" / "axe.min.js"
    axe_asset.parent.mkdir(parents=True, exist_ok=True)
    axe_asset.write_text("", encoding="utf-8")
    monkeypatch.setenv("AXE_CORE_ASSET", str(axe_asset))

    contracts = {
        _EVENT_REPORT: event_contract,
        _GOLDEN_REPORT: golden_contract,
    }
    snapshot_files = {
        "index.html": "<!DOCTYPE html><html></html>",
        ".nojekyll": "",
        _EVENT_REPORT: _report_html(event_stats),
        _GOLDEN_REPORT: _report_html(golden_stats),
    }

    def fake_run_git(
        actual_repo: Path,
        arguments: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        assert actual_repo == repo_root.resolve()
        if arguments[:2] == ["cat-file", "-e"]:
            assert not check
        elif arguments[:2] == ["worktree", "add"]:
            snapshot_root = Path(arguments[3])
            for relative, content in snapshot_files.items():
                destination = snapshot_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
        elif arguments[:2] == ["worktree", "remove"]:
            assert not check
        else:
            raise AssertionError(f"unexpected Git command: {arguments}")
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(report_checks, "run_git", fake_run_git)
    _install_fake_playwright(monkeypatch, contracts)


def test_snapshot_check_parses_safe_stats_and_reconciles_activity_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Escaped JSON stats and visible activity totals pass the public checker."""
    stats = _activity_stats()
    stats["display_text"] = "<synthetic> &"
    _configure_checker(
        tmp_path,
        monkeypatch,
        event_stats=stats,
        event_contract=_activity_contract(),
    )

    result = report_checks.check_committed_snapshot(tmp_path, _SHA)

    assert result["success"] is True
    assert len(result["reports"]) == 2


def test_snapshot_check_rejects_mismatched_card_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A displayed Quest Types row cannot disagree with embedded counts."""
    contract = _activity_contract()
    contract["cards"]["qt-heading"]["rowCounts"] = ["1"]
    _configure_checker(
        tmp_path,
        monkeypatch,
        event_stats=_activity_stats(),
        event_contract=contract,
    )

    with pytest.raises(PublicationError, match="rows do not match"):
        report_checks.check_committed_snapshot(tmp_path, _SHA)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("changeset_count", "2", "non-negative integer"),
        (
            "questions_answered",
            [None],
            r"questions_answered\[0\] must be an object",
        ),
        ("features_created", "invalid", "features_created must be a list"),
    ],
)
def test_snapshot_check_rejects_malformed_embedded_stats(
    field: str,
    value: object,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed embedded counts and row collections fail clearly."""
    stats = _activity_stats()
    stats[field] = value
    _configure_checker(
        tmp_path,
        monkeypatch,
        event_stats=stats,
        event_contract=_activity_contract(),
    )

    with pytest.raises(PublicationError, match=message):
        report_checks.check_committed_snapshot(tmp_path, _SHA)


def test_snapshot_check_reconciles_aggregate_totals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aggregate event and attributed contributor totals remain consistent."""
    stats: dict[str, Any] = {
        "report_type": "aggregate",
        "contributor_count": 2,
        "quest_answer_count": 5,
        "note_count": 3,
        "unattributed_note_count": 1,
        "new_feature_count": 4,
        "event_count": 2,
    }
    _configure_checker(
        tmp_path,
        monkeypatch,
        event_stats=stats,
        event_contract=_aggregate_contract(),
    )

    result = report_checks.check_committed_snapshot(tmp_path, _SHA)

    assert result["success"] is True


def test_snapshot_check_requires_independent_golden_sample_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The published Golden Sample cannot silently drift from its fixture contract."""
    _configure_checker(
        tmp_path,
        monkeypatch,
        event_stats=_activity_stats(),
        event_contract=_activity_contract(),
        golden_stats={"changeset_count": 2},
    )

    with pytest.raises(PublicationError, match="Golden Sample changeset_count"):
        report_checks.check_committed_snapshot(tmp_path, _SHA)
