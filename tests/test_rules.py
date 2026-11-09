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


def test_user_a_cannot_modify_user_b_rules(client, db_session, test_user, auth_headers):
    """Test that User A updating rules does not modify or overwrite User B's rules."""
    user_b = User(
        email="trader_b@example.com",
        password_hash=hash_password("PasswordB123!"),
        display_name="Trader B",
        is_active=True,
    )
    db_session.add(user_b)
    db_session.commit()

    token_b = create_access_token(subject=str(user_b.id))
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B sets rules
    client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 1.5,
            "max_trades_per_day": 3,
            "no_averaging_down": True,
            "max_position_pct": 10.0,
            "practice_capital": 50000.0,
        },
        headers=headers_b,
    )

    # User A sets rules
    client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 4.0,
            "max_trades_per_day": 10,
            "no_averaging_down": False,
            "max_position_pct": 25.0,
            "practice_capital": 300000.0,
        },
        headers=auth_headers,
    )

    # Verify User B rules remained unchanged
    res_b = client.get("/api/v1/rules/current", headers=headers_b)
    assert res_b.status_code == status.HTTP_200_OK
    assert res_b.json()["stop_loss_pct"] == 1.5
    assert res_b.json()["max_trades_per_day"] == 3
    assert res_b.json()["practice_capital"] == 50000.0

    # Verify User A rules are separate
    res_a = client.get("/api/v1/rules/current", headers=auth_headers)
    assert res_a.status_code == status.HTTP_200_OK
    assert res_a.json()["stop_loss_pct"] == 4.0


def test_two_users_isolated_rules_and_empty_progress(client, db_session, sample_scenario):
    """Verifies that two test users each see only their own rules and an empty progress page."""
    # Register User 1
    signup1 = client.post(
        "/api/v1/auth/signup",
        json={"email": "alice@example.com", "password": "Password123!", "display_name": "Alice"},
    )
    assert signup1.status_code == status.HTTP_201_CREATED
    login1 = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "Password123!"},
    )
    headers1 = {"Authorization": f"Bearer {login1.json()['access_token']}"}

    # Register User 2
    signup2 = client.post(
        "/api/v1/auth/signup",
        json={"email": "bob@example.com", "password": "Password123!", "display_name": "Bob"},
    )
    assert signup2.status_code == status.HTTP_201_CREATED
    login2 = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "Password123!"},
    )
    headers2 = {"Authorization": f"Bearer {login2.json()['access_token']}"}

    # Both start with empty progress dashboard
    dash1 = client.get("/api/v1/progress/dashboard", headers=headers1)
    dash2 = client.get("/api/v1/progress/dashboard", headers=headers2)
    assert dash1.status_code == status.HTTP_200_OK
    assert dash1.json()["status"] == "empty"
    assert dash1.json()["total_decisions"] == 0
    assert dash2.status_code == status.HTTP_200_OK
    assert dash2.json()["status"] == "empty"
    assert dash2.json()["total_decisions"] == 0

    # Alice sets rules: Stop Loss 2.0%
    client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 2.0,
            "max_trades_per_day": 5,
            "no_averaging_down": True,
            "max_position_pct": 20.0,
            "practice_capital": 100000.0,
        },
        headers=headers1,
    )

    # Bob sets rules: Stop Loss 3.5%
    client.post(
        "/api/v1/rules",
        json={
            "stop_loss_pct": 3.5,
            "max_trades_per_day": 7,
            "no_averaging_down": False,
            "max_position_pct": 15.0,
            "practice_capital": 50000.0,
        },
        headers=headers2,
    )

    # Alice sees only Alice's rules
    alice_rule = client.get("/api/v1/rules/current", headers=headers1).json()
    assert alice_rule["stop_loss_pct"] == 2.0

    # Bob sees only Bob's rules
    bob_rule = client.get("/api/v1/rules/current", headers=headers2).json()
    assert bob_rule["stop_loss_pct"] == 3.5

    # Alice submits a decision
    client.post(
        "/api/v1/decisions",
        json={
            "scenario_id": sample_scenario.id,
            "action": "hold",
            "size": 10000.0,
            "reason": "Followed my rule",
            "decision_seconds": 4.5,
            "chart_viewed": True,
            "after_reveal": False,
        },
        headers=headers1,
    )

    # Alice has 1 decision
    alice_dash = client.get("/api/v1/progress/dashboard", headers=headers1).json()
    assert alice_dash["total_decisions"] == 1

    # Bob still has 0 decisions and empty status
    bob_dash = client.get("/api/v1/progress/dashboard", headers=headers2).json()
    assert bob_dash["status"] == "empty"
    assert bob_dash["total_decisions"] == 0

