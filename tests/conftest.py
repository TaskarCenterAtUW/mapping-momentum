"""tests/conftest.py — shared pytest configuration."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests that make live API calls.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(
            reason="Pass --run-integration to run live API tests."
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)
