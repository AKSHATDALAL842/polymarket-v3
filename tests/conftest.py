# tests/conftest.py
"""
Shared pytest fixtures for the test suite.
"""
import pytest
import config


@pytest.fixture(autouse=True)
def reset_config_dry_run():
    """Reset config.DRY_RUN to True before each test to ensure isolation."""
    original = config.DRY_RUN
    config.DRY_RUN = True
    yield
    config.DRY_RUN = original
