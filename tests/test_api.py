"""Tests for root endpoints, health checks, and cross-origin headers."""

from fastapi import status


def test_root_endpoint(client):
    """Test root application status."""
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["app"] == "TradeZen Scenario Coach"
    assert data["status"] == "online"


def test_health_check(client):
    """Test health check probe."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"


def test_cors_headers(client):
    """Test CORS headers on pre-flight request."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://192.168.1.100:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    assert "access-control-allow-origin" in response.headers
