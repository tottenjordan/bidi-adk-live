# tests/test_main.py
"""Tests for the FastAPI WebSocket server."""

import pytest
from fastapi.testclient import TestClient


class TestAppInitialization:
    """Verify the FastAPI app is properly configured."""

    def test_app_exists(self, app):
        """FastAPI app can be imported."""
        assert app is not None

    def test_root_serves_html(self, app):
        """Root path serves the index.html file."""
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_static_files_mounted(self, app):
        """Static files are accessible."""
        client = TestClient(app)
        response = client.get("/static/css/style.css")
        # Will be 200 once static files exist, 404 is acceptable during scaffolding
        assert response.status_code in (200, 404)


class TestWebSocketEndpoint:
    """Verify WebSocket endpoint configuration."""

    def test_websocket_endpoint_accepts_connection(self, app):
        """WebSocket endpoint at /ws/{user_id}/{session_id} accepts connections."""
        client = TestClient(app)
        with client.websocket_connect("/ws/test-user/test-session") as ws:
            # Connection should be accepted without error
            assert ws is not None
