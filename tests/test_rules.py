"""Tests for user rules, versioning, and user data isolation."""

import pytest
from fastapi import status
from app.models.user import User
from app.models.rule import Rule
from app.core.security import hash_password, create_access_token


def test_set_and_get_rules(client, auth_headers):
    """Test creating and reading personal trading rules."""
    payload = {
        "stop_loss_pct": 2.5,
        "max_trades_per_day": 4,
        "no_averaging_down": True,
        "max_position_pct": 15.0,
        "practice_capital": 50000.0,
    }
    create_res = client.post("/api/v1/rules", json=payload, headers=auth_headers)
    assert create_res.status_code == status.HTTP_201_CREATED
    data = create_res.json()
    assert data["version"] == 1
    assert data["is_current"] is True
    assert data["stop_loss_pct"] == 2.5

    # Fetch active rule
    get_res = client.get("/api/v1/rules/current", headers=auth_headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["stop_loss_pct"] == 2.5


def test_rule_versioning_history(client, auth_headers):
    """Test updating rules creates a new version while archiving the older version."""
    # Version 1
    client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 2.0,
            "max_trades_per_day": 5,
            "no_averaging_down": True,
            "max_position_pct": 20.0,
            "practice_capital": 100000.0,
        },
        headers=auth_headers,
    )

    # Version 2
    update_res = client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 1.5,
            "max_trades_per_day": 3,
            "no_averaging_down": True,
            "max_position_pct": 10.0,
            "practice_capital": 100000.0,
        },
        headers=auth_headers,
    )
    assert update_res.status_code == status.HTTP_201_CREATED
    assert update_res.json()["version"] == 2

    # Fetch history
    history_res = client.get("/api/v1/rules/history", headers=auth_headers)
    assert history_res.status_code == status.HTTP_200_OK
    versions = history_res.json()
    assert len(versions) == 2
    assert versions[0]["version"] == 2
    assert versions[0]["is_current"] is True
    assert versions[1]["version"] == 1
    assert versions[1]["is_current"] is False


def test_user_data_isolation(client, db_session, test_user, auth_headers):
    """Test that User A cannot view or modify User B's rules."""
    # Create User B
    user_b = User(
        email="user_b@example.com",
        password_hash=hash_password("PasswordB123!"),
        display_name="User B",
        is_active=True,
    )
    db_session.add(user_b)
    db_session.commit()

    token_b = create_access_token(subject=str(user_b.id))
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates rules
    client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 3.0,
            "max_trades_per_day": 8,
            "no_averaging_down": False,
            "max_position_pct": 30.0,
            "practice_capital": 200000.0,
        },
        headers=auth_headers,
    )

    # User B queries their rules - should be empty / None
    res_b = client.get("/api/v1/rules/current", headers=headers_b)
    assert res_b.status_code == status.HTTP_200_OK
    assert res_b.json() is None
