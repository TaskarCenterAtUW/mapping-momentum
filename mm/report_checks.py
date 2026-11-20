"""Local browser and accessibility checks for a committed report snapshot."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeGuard, cast

from mm.common.io import write_json
from mm.publication import (
    PublicationError,
    candidate_check_path,
    full_sha,
    publication_allowlist,
    run_git,
)


def _is_json_object(value: object) -> TypeGuard[dict[str, Any]]:
    """Narrow decoded JSON objects to string-keyed dictionaries."""
    if not isinstance(value, dict):
        return False
    object_items = cast(dict[object, object], value)
    return all(isinstance(key, str) for key in object_items)


def _report_rows(
    stats: dict[str, Any],
    field: str,
    relative: str,
) -> list[dict[str, Any]]:
    """Return one report-stat field as validated object records."""
    value: object = stats.get(field, [])
    if not isinstance(value, list):
        raise PublicationError(
            f"{relative}: embedded report stats {field} must be a list"
        )

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(cast(list[object], value)):
        if not _is_json_object(row):
            raise PublicationError(
                f"{relative}: embedded report stats {field}[{index}] must be an object"
            )
        rows.append(row)
    return rows


def _nonnegative_count(value: object, field: str, relative: str) -> int:
    """Validate an embedded report count before using it in reconciliation."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PublicationError(
            f"{relative}: embedded report count {field} must be a non-negative integer"
        )
    return value


def _stat_count(
    stats: dict[str, Any],
    field: str,
    relative: str,
    *,
    default: int | None = None,
) -> int:
    """Read a required or defaulted integer count from embedded stats."""
    if field in stats:
        value: object = stats[field]
    elif default is not None:
        value = default
    else:
        raise PublicationError(f"{relative}: embedded report stats are missing {field}")
    return _nonnegative_count(value, field, relative)


def _row_count(
    row: dict[str, Any],
    field: str,
    relative: str,
    *,
    default: int | None = None,
) -> int:
    """Read a required or defaulted count from one embedded stats row."""
    if field in row:
        value: object = row[field]
    elif default is not None:
        value = default
    else:
        raise PublicationError(f"{relative}: embedded report row is missing {field}")
    return _nonnegative_count(value, field, relative)


def _report_version(repo_root: Path) -> str:
    """Read the footer version from pyproject.toml."""
    import tomllib

    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise PublicationError("pyproject.toml must define a non-empty project version")
    return version.strip()


def _all_files(root: Path) -> set[str]:
    """Return the exact regular-file allowlist below one snapshot root."""
    files: set[str] = set()
    for path in root.rglob("*"):
        if path.name == ".git":
            continue
        if path.is_symlink():
            raise PublicationError(f"refusing symlink in snapshot: {path}")
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def _safe_screenshot_name(relative: str) -> str:
    """Create a bounded screenshot filename from a relative report path."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", relative)
    return name[:180].rstrip("-") + ".png"


def _embedded_stats(html: str) -> dict[str, Any]:
    """Extract the safe JSON stats object embedded in a rendered report."""
    marker = "const STATS = "
    start = html.find(marker)
    if start == -1:
        raise PublicationError("report does not contain its embedded stats object")
    decoded_value, _ = json.JSONDecoder().raw_decode(
        html[start + len(marker) :].lstrip()
    )
    value: object = decoded_value
    if not _is_json_object(value):
        raise PublicationError("embedded report stats must be a JSON object")
    return value


def _displayed_integer(value: Any, field: str) -> int:
    """Convert one displayed report value to an integer."""
    if not isinstance(value, str) or not re.fullmatch(r"\d+", value.strip()):
        raise PublicationError(f"invalid displayed integer for {field}: {value!r}")
    return int(value.strip())


def _validate_report_contract(
    stats: dict[str, Any],
    contract: dict[str, Any],
    relative: str,
) -> None:
    """Reconcile visible report values and controls with embedded report data."""
    # Every published page declares English, has one primary heading, and
    # exposes the complete-document export control to keyboard users.
    if contract["lang"] != "en":
        raise PublicationError(f"{relative}: html lang must be en")
    if contract["h1Count"] != 1:
        raise PublicationError(f"{relative}: expected exactly one h1")
    if not contract["exportPresent"] or not contract["exportFilename"]:
        raise PublicationError(f"{relative}: missing Save / Export control")

    summary: dict[str, Any] = contract.get("summary", {})
    cards: dict[str, Any] = contract.get("cards", {})
    if stats.get("report_type") == "aggregate":
        # Aggregate summary totals exactly reflect the embedded aggregate model.
        expected_summary: dict[str, int] = {
            "Contributors": _stat_count(stats, "contributor_count", relative),
            "Quest answers": _stat_count(stats, "quest_answer_count", relative),
            "Notes": _stat_count(stats, "note_count", relative),
            "New map features": _stat_count(stats, "new_feature_count", relative),
            "Events": _stat_count(stats, "event_count", relative),
        }
        for label, expected in expected_summary.items():
            actual = _displayed_integer(summary.get(label), f"{relative} {label}")
            if actual != expected:
                raise PublicationError(
                    f"{relative}: {label} displays {actual}, expected {expected}"
                )

        # Event and contributor rows reconcile with aggregate contribution totals.
        event_total = sum(
            _displayed_integer(value, f"{relative} event total")
            for value in contract.get("eventTotals", [])
        )
        expected_total = _stat_count(
            stats, "quest_answer_count", relative
        ) + _stat_count(stats, "note_count", relative)
        if event_total != expected_total:
            raise PublicationError(
                f"{relative}: event contribution total {event_total} "
                f"does not equal {expected_total}"
            )
        contributor_total = sum(
            _displayed_integer(value, f"{relative} contributor total")
            for value in contract.get("contributorTotals", [])
        )
        expected_attributed_total = expected_total - _stat_count(
            stats,
            "unattributed_note_count",
            relative,
            default=0,
        )
        if contributor_total != expected_attributed_total:
            raise PublicationError(
                f"{relative}: contributor total {contributor_total} "
                f"does not equal attributed total {expected_attributed_total}"
            )
        return

    # Activity summary cards exactly reflect the embedded source statistics.
    questions_answered = _report_rows(stats, "questions_answered", relative)
    contributors = _report_rows(stats, "contributors_breakdown", relative)
    features_created = _report_rows(stats, "features_created", relative)
    expected_summary: dict[str, int] = {
        "Changesets": _stat_count(stats, "changeset_count", relative, default=0),
        "Questions answered": sum(
            _row_count(category, "total", relative, default=0)
            for category in questions_answered
        ),
        "Contributors": len(contributors),
        "Notes": _stat_count(stats, "note_count", relative, default=0),
        "New map features": sum(
            _row_count(item, "count", relative, default=0) for item in features_created
        ),
    }
    for label, expected in expected_summary.items():
        actual = _displayed_integer(summary.get(label), f"{relative} {label}")
        if actual != expected:
            raise PublicationError(
                f"{relative}: {label} displays {actual}, expected {expected}"
            )

    # Quest type, feature, and contributor card totals reconcile with rows.
    expected_cards: dict[str, list[dict[str, Any]]] = {
        "qt-heading": _report_rows(stats, "quest_type_breakdown", relative),
        "fc-heading": features_created,
        "cb-heading": contributors,
    }
    for heading, rows in expected_cards.items():
        card = cards.get(heading, {})
        expected_row_counts = [_row_count(row, "count", relative) for row in rows]
        expected_count = (
            len(rows) if heading == "cb-heading" else sum(expected_row_counts)
        )
        displayed_count = _displayed_integer(
            card.get("count"),
            f"{relative} {heading} card count",
        )
        displayed_rows = [
            _displayed_integer(value, f"{relative} {heading} row")
            for value in card.get("rowCounts", [])
        ]
        if displayed_count != expected_count:
            raise PublicationError(
                f"{relative}: {heading} displays {displayed_count}, "
                f"expected {expected_count}"
            )
        if displayed_rows != expected_row_counts:
            raise PublicationError(
                f"{relative}: {heading} rows do not match embedded stats"
            )

    # The Questions Answered total equals all displayed category totals.
    question_total = sum(
        _row_count(category, "total", relative, default=0)
        for category in questions_answered
    )
    displayed_question_total = _displayed_integer(
        contract.get("questionTotal"),
        f"{relative} question total",
    )
    if displayed_question_total != question_total:
        raise PublicationError(
            f"{relative}: displayed question total {displayed_question_total} "
            f"does not equal {question_total}"
        )


def _validate_golden_sample(stats: dict[str, Any], relative: str) -> None:
    """Assert independently specified known values for the Golden Sample."""
    if relative != "golden-sample/index.html":
        return
    expected: dict[str, object] = {
        "changeset_count": 3,
        "contributor_count": 3,
        "elements_edited": 3,
        "features_created": [
            {"feature_type": "node", "count": 1},
            {"feature_type": "way", "count": 1},
        ],
        "node_count": 2,
        "note_count": 2,
        "quest_type_breakdown": [
            {"category": "Synthetic Surfaces", "count": 2, "photo_count": 2},
            {"category": "Synthetic Crossings", "count": 1, "photo_count": 0},
        ],
        "relation_count": 0,
        "way_count": 1,
    }
    for field, expected_value in expected.items():
        if stats.get(field) != expected_value:
            raise PublicationError(
                f"{relative}: Golden Sample {field} is "
                f"{stats.get(field)!r}, expected {expected_value!r}"
            )


def _create_collage(
    screenshots: list[tuple[str, Path]],
    destination: Path,
) -> None:
    """Create a labeled screenshot collage with Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError as exc:
        raise PublicationError(
            "Pillow is required for report screenshot collages"
        ) from exc

    if not screenshots:
        raise PublicationError("no report screenshots were produced")

    opened: list[tuple[str, Image.Image]] = []
    max_width = 720
    for label, path in screenshots:
        image: Image.Image = Image.open(path).convert("RGB")
        scale = min(1.0, max_width / image.width)
        if scale < 1.0:
            image = ImageOps.scale(image, scale)
        opened.append((label, image))

    content_width = max(image.width for _, image in opened)
    label_height = 36
    margin = 16
    height = sum(label_height + image.height for _, image in opened)
    canvas = Image.new(
        "RGB",
        (content_width + margin * 2, height + margin * 2),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    y = margin
    for label, image in opened:
        draw.text((margin, y + 8), label, fill="black")
        y += label_height
        canvas.paste(image, (margin, y))
        y += image.height
    canvas.save(destination, format="PNG")


def check_committed_snapshot(
    repo_root: Path,
    sha: str,
) -> dict[str, Any]:
    """Run local contract, accessibility, keyboard, export, and screenshot checks."""
    repo_root = repo_root.resolve()
    sha = full_sha(sha)
    cat_file = run_git(
        repo_root,
        ["cat-file", "-e", f"{sha}^{{commit}}"],
        check=False,
    )
    if cat_file.returncode != 0:
        raise PublicationError(f"{sha} does not resolve to a local commit")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PublicationError(
            "Python Playwright is required for report checks"
        ) from exc

    axe_asset_value = os.environ.get("AXE_CORE_ASSET")
    axe_asset = (
        Path(axe_asset_value).resolve()
        if axe_asset_value
        else repo_root / "tests" / "vendor" / "axe.min.js"
    )
    if not axe_asset.is_file():
        raise PublicationError(f"axe-core asset is missing: {axe_asset}")

    output_root = candidate_check_path(repo_root, sha).parent
    output_root.mkdir(parents=True, exist_ok=True)
    screenshot_root = output_root / "screenshots"
    if screenshot_root.exists():
        shutil.rmtree(screenshot_root)
    screenshot_root.mkdir(parents=True, exist_ok=True)

    local_storage = repo_root / "local-storage"
    local_storage.mkdir(parents=True, exist_ok=True)
    report_version = _report_version(repo_root)

    with tempfile.TemporaryDirectory(
        prefix="mapping-momentum-check-",
        dir=local_storage,
    ) as temp_name:
        snapshot_root = Path(temp_name) / "snapshot"
        snapshot_root.mkdir()
        run_git(
            repo_root,
            ["worktree", "add", "--detach", str(snapshot_root), sha],
        )

        try:
            _, expected_paths = publication_allowlist(
                repo_root,
                snapshot_root,
            )
            actual_files = _all_files(snapshot_root)
            expected_files = set(expected_paths)
            if actual_files != expected_files:
                missing = sorted(expected_files - actual_files)
                unexpected = sorted(actual_files - expected_files)
                raise PublicationError(
                    "committed snapshot allowlist mismatch"
                    + (f"; missing: {', '.join(missing)}" if missing else "")
                    + (f"; unexpected: {', '.join(unexpected)}" if unexpected else "")
                )

            report_paths = [
                path
                for path in snapshot_root.rglob("index.html")
                if path != snapshot_root / "index.html"
            ]
            if not report_paths:
                raise PublicationError("snapshot contains no report HTML documents")

            report_results: list[dict[str, Any]] = []
            screenshot_entries: list[tuple[str, Path]] = []

            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(headless=True)
                except Exception as exc:
                    raise PublicationError(
                        "Playwright Chromium could not launch; "
                        "run `python -m playwright install chromium`"
                    ) from exc

                try:
                    for report_path in sorted(report_paths):
                        relative = report_path.relative_to(snapshot_root).as_posix()
                        stats = _embedded_stats(report_path.read_text(encoding="utf-8"))
                        _validate_golden_sample(stats, relative)
                        page = browser.new_page(
                            viewport={"width": 1440, "height": 1000}
                        )
                        page.goto(report_path.as_uri(), wait_until="domcontentloaded")
                        page.wait_for_timeout(500)

                        contract = page.evaluate(
                            """() => {
                              const h1 = document.querySelectorAll("h1");
                              const exportButton = document.querySelector(
                                "[data-export-report]"
                              );
                              const summary = Object.fromEntries(
                                Array.from(
                                  document.querySelectorAll(".metric-card")
                                ).map(card => [
                                  card.querySelector(".metric-label")
                                    ?.textContent.trim(),
                                  card.querySelector(".metric-value")
                                    ?.textContent.trim()
                                ]).filter(item => item[0])
                              );
                              const card = heading => {
                                const section = document.querySelector(
                                  `[aria-labelledby="${heading}"]`
                                );
                                return {
                                  count: section
                                    ? section.querySelector(".card-count")
                                      ?.textContent.trim().split(" ")[0]
                                    : null,
                                  rowCounts: section
                                    ? Array.from(
                                      section.querySelectorAll(
                                        ".breakdown-table tbody .bar-value"
                                      )
                                    ).map(item => item.textContent.trim())
                                    : []
                                };
                              };
                              return {
                                lang: document.documentElement.lang,
                                h1Count: h1.length,
                                title: document.title,
                                footer: document.querySelector(".report-footer")
                                  ? document.querySelector(
                                    ".report-footer"
                                  ).textContent
                                  : "",
                                exportPresent: Boolean(exportButton),
                                exportFilename: exportButton
                                  ? exportButton.dataset.exportFilename
                                  : null,
                                summary,
                                cards: {
                                  "qt-heading": card("qt-heading"),
                                  "fc-heading": card("fc-heading"),
                                  "cb-heading": card("cb-heading")
                                },
                                questionTotal: document.querySelector(
                                  '[aria-labelledby="qa-heading"] .card-count'
                                )?.textContent.trim().split(" ")[0],
                                eventTotals: Array.from(
                                  document.querySelectorAll(".event-total")
                                ).map(item => item.textContent.trim()),
                                contributorTotals: Array.from(
                                  document.querySelectorAll(
                                    ".contributor-table tbody tr"
                                  )
                                ).map(row => {
                                  const cells = row.querySelectorAll("td.numeric");
                                  return cells.length
                                    ? cells[cells.length - 1].textContent.trim()
                                    : "0";
                                }),
                                resourceUrls: Array.from(
                                  document.querySelectorAll(
                                    "img[src], iframe[src], video source[src]"
                                  )
                                ).map(element => element.getAttribute("src"))
                                 .filter(Boolean)
                              };
                            }"""
                        )

                        _validate_report_contract(stats, contract, relative)
                        # The footer identifies the exact source version used to
                        # render each published report.
                        footer_version = f"Mapping Momentum v{report_version}"
                        if footer_version not in contract["footer"]:
                            raise PublicationError(
                                f"{relative}: footer version is not v{report_version}"
                            )
                        # A saved report remains usable because displayed media
                        # is absolute or already embedded in the document.
                        for resource_url in contract["resourceUrls"]:
                            if not resource_url or not resource_url.startswith(
                                ("data:", "https://", "http://")
                            ):
                                raise PublicationError(
                                    f"{relative}: saved-file resource is not "
                                    f"absolute or embedded: {resource_url}"
                                )

                        page.add_script_tag(path=str(axe_asset))
                        axe = page.evaluate(
                            """async () => await axe.run(document, {
                              runOnly: {
                                type: "tag",
                                values: [
                                  "wcag2a",
                                  "wcag2aa",
                                  "wcag21a",
                                  "wcag21aa",
                                  "wcag22aa"
                                ]
                              }
                            })"""
                        )
                        violations = axe.get("violations", [])
                        if violations:
                            names = [
                                f"{item.get('id')}: {item.get('description')}"
                                for item in violations
                            ]
                            raise PublicationError(
                                f"{relative}: axe violations: " + "; ".join(names)
                            )

                        theme_light = page.query_selector(
                            '.report-theme-button[data-theme-mode="light"]'
                        )
                        if theme_light:
                            theme_light.focus()
                            page.keyboard.press("Enter")
                            theme_state = page.evaluate(
                                """() => ({
                                  mode: document.documentElement.dataset.themeMode,
                                  theme: document.documentElement.dataset.theme,
                                  pressed: document.querySelector(
                                    '.report-theme-button[data-theme-mode="light"]'
                                  ).getAttribute("aria-pressed")
                                })"""
                            )
                            if (
                                theme_state["mode"] != "light"
                                or theme_state["theme"] != "light"
                                or theme_state["pressed"] != "true"
                            ):
                                raise PublicationError(
                                    f"{relative}: keyboard theme activation failed"
                                )

                        skip_link = page.query_selector(".skip-link")
                        if skip_link:
                            skip_link.focus()
                            page.keyboard.press("Enter")
                            if page.evaluate("location.hash") != "#main-content":
                                raise PublicationError(
                                    f"{relative}: keyboard skip link failed"
                                )

                        resize_handle = page.query_selector("#map-resize-handle")
                        if resize_handle:
                            resize_before = int(
                                resize_handle.get_attribute("aria-valuenow") or "0"
                            )
                            resize_handle.focus()
                            page.keyboard.press("ArrowDown")
                            resize_after = int(
                                resize_handle.get_attribute("aria-valuenow") or "0"
                            )
                            if resize_after <= resize_before:
                                raise PublicationError(
                                    f"{relative}: keyboard map resize failed"
                                )

                        expand_button = page.query_selector("#btn-expand")
                        if expand_button:
                            expand_button.focus()
                            page.keyboard.press("Enter")
                            if expand_button.get_attribute("aria-expanded") != "true":
                                raise PublicationError(
                                    f"{relative}: keyboard map expansion failed"
                                )

                        question_details = page.query_selector(".cat-details")
                        if question_details:
                            question_summary = question_details.query_selector(
                                ".cat-summary"
                            )
                            if question_summary:
                                question_summary.focus()
                                page.keyboard.press("Enter")
                                if not question_details.get_attribute("open") == "":
                                    raise PublicationError(
                                        f"{relative}: keyboard question "
                                        "expansion failed"
                                    )

                        showcase_button = page.query_selector(".showcase-btn")
                        if showcase_button:
                            showcase_button.focus()
                            page.keyboard.press("Enter")
                            if not page.locator("#photo-modal").evaluate(
                                "(dialog) => dialog.open"
                            ):
                                raise PublicationError(
                                    f"{relative}: keyboard gallery opening failed"
                                )
                            page.keyboard.press("Escape")
                            if page.locator("#photo-modal").evaluate(
                                "(dialog) => dialog.open"
                            ):
                                raise PublicationError(
                                    f"{relative}: keyboard gallery closing failed"
                                )

                        export_button = page.query_selector("[data-export-report]")
                        exported_path = (
                            Path(
                                tempfile.mkdtemp(
                                    prefix="mapping-momentum-export-",
                                    dir=local_storage,
                                )
                            )
                            / contract["exportFilename"]
                        )
                        if export_button:
                            with page.expect_download(timeout=30000) as download_info:
                                export_button.press("Enter")
                            download = download_info.value
                            download.save_as(str(exported_path))

                        if not exported_path.is_file():
                            raise PublicationError(
                                f"{relative}: export download was not produced"
                            )
                        exported_html = exported_path.read_text(encoding="utf-8")
                        if not exported_html.startswith("<!DOCTYPE html>"):
                            raise PublicationError(
                                f"{relative}: exported document lacks doctype"
                            )

                        fresh_page = browser.new_page()
                        fresh_page.goto(
                            exported_path.as_uri(),
                            wait_until="domcontentloaded",
                        )
                        fresh_contract = fresh_page.evaluate(
                            """() => ({
                              title: document.title,
                              h1Count: document.querySelectorAll("h1").length,
                              exportPresent: Boolean(
                                document.querySelector("[data-export-report]")
                              ),
                              resourceUrls: Array.from(
                                document.querySelectorAll(
                                  "img[src], iframe[src], video source[src]"
                                )
                              ).map(element => element.getAttribute("src"))
                               .filter(Boolean)
                            })"""
                        )
                        if (
                            fresh_contract["h1Count"] != 1
                            or not fresh_contract["exportPresent"]
                            or fresh_contract["title"] != contract["title"]
                        ):
                            raise PublicationError(
                                f"{relative}: exported document failed fresh-context "
                                "load"
                            )
                        for resource_url in fresh_contract["resourceUrls"]:
                            if not resource_url or not resource_url.startswith(
                                ("data:", "https://", "http://")
                            ):
                                raise PublicationError(
                                    f"{relative}: exported resource is not "
                                    f"absolute or embedded: {resource_url}"
                                )
                        fresh_page.close()

                        screenshot_name = _safe_screenshot_name(relative)
                        screenshot_path = screenshot_root / screenshot_name
                        page.screenshot(
                            path=str(screenshot_path),
                            full_page=True,
                        )
                        screenshot_entries.append((relative, screenshot_path))
                        report_results.append(
                            {
                                "path": relative,
                                "h1_count": contract["h1Count"],
                                "axe_violation_count": len(violations),
                                "keyboard_theme": True,
                                "keyboard_skip_link": bool(skip_link),
                                "keyboard_map_resize": bool(resize_handle),
                                "keyboard_map_expand": bool(expand_button),
                                "keyboard_question_expansion": bool(question_details),
                                "keyboard_gallery": bool(showcase_button),
                                "export_download": True,
                                "fresh_export_load": True,
                                "screenshot": screenshot_name,
                            }
                        )
                        page.close()
                finally:
                    browser.close()

            collage_path = output_root / "collage.png"
            _create_collage(screenshot_entries, collage_path)

            result: dict[str, Any] = {
                "success": True,
                "sha": sha,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "project_version": report_version,
                "axe_asset": str(axe_asset),
                "reports": report_results,
                "collage": "collage.png",
                "privacy_review": "pending_interactive_confirmation",
            }
            write_json(candidate_check_path(repo_root, sha), result)
            return result
        finally:
            run_git(
                repo_root,
                ["worktree", "remove", "--force", str(snapshot_root)],
                check=False,
            )
