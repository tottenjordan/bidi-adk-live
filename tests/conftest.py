# tests/conftest.py
"""Shared test fixtures."""

import pytest


@pytest.fixture
def app():
    """Import and return the FastAPI app."""
    from app.main import app
    return app
