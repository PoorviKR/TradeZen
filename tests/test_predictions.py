"""Tests for ML predictions, rating feedback, and dashboard progress."""

import pytest
from fastapi import status
from app.models.scenario import Scenario
from app.models.decision import Prediction


def test_rate_prediction_feedback(client, auth_headers, sample_scenario):
    """Test user rating endpoint: 'was this feedback right? yes/no'."""
    # First submit a decision to create attempt and prediction
    decision_payload = {
        "scenario_id": sample_scenario.id,
        "action": "buy",
        "size": 5000.0,
        "reason": "Fear",
        "decision_seconds": 3.0,
        "chart_viewed": True,
        "after_reveal": False,
    }
    submit_res = client.post("/api/v1/decisions", json=decision_payload, headers=auth_headers)
    assert submit_res.status_code == status.HTTP_201_CREATED

    # Rate feedback as correct (yes)
    rate_res = client.post(
        "/api/v1/predictions/1/feedback",
        json={"feedback_correct": True},
        headers=auth_headers,
    )
    assert rate_res.status_code == status.HTTP_200_OK
    assert "Thank you" in rate_res.json()["message"]


def test_dashboard_empty_and_active_states(client, auth_headers, sample_scenario):
    """Test dashboard response when empty and after decisions are recorded."""
    # Check dashboard
    dash_res = client.get("/api/v1/progress/dashboard", headers=auth_headers)
    assert dash_res.status_code == status.HTTP_200_OK
    data = dash_res.json()
    assert data["status"] in ["empty", "active"]


def test_login_rate_limiting(client, test_user):
    """Test that 5 failed logins within 15 minutes triggers HTTP 429 Too Many Requests."""
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "WrongPassword!"},
        )

    # 6th attempt must be blocked with 429
    res = client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "WrongPassword!"},
    )
    assert res.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Too many failed login attempts" in res.json()["detail"]
