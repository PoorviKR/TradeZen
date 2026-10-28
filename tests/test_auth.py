"""Tests for user authentication endpoints and rate limiting."""

import pytest
from fastapi import status


def test_signup_success(client):
    """Test successful user registration."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "trader1@example.com",
            "password": "StrongPassword123!",
            "display_name": "Trader One",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == "trader1@example.com"
    assert data["display_name"] == "Trader One"
    assert "password_hash" not in data


def test_signup_duplicate_email(client, test_user):
    """Test that signing up with an already registered email fails."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": test_user.email,
            "password": "Password123!",
            "display_name": "Duplicate Trader",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "already exists" in response.json()["detail"]


def test_login_success(client, test_user):
    """Test valid credentials return access token and set cookies."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "Password123!"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == test_user.email
    assert "tradezen_access_token" in response.cookies


def test_login_wrong_password(client, test_user):
    """Test login with incorrect password is rejected."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "WrongPassword999!"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid email or password" in response.json()["detail"]


def test_get_current_user_profile(client, auth_headers, test_user):
    """Test authenticated access to /auth/me."""
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["email"] == test_user.email


def test_unauthenticated_request_rejected(client):
    """Test that protected endpoint fails without token."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
