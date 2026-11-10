"""Tests for user authentication endpoints, standardized identity, and rate limiting."""

import pytest
from datetime import timedelta
from fastapi import status

from app.core.security import create_access_token, create_refresh_token


def test_signup_success(client):
    """Test successful user registration and auto-derived canonical username."""
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
    assert "username" in data
    assert data["username"] == "trader_one"
    assert "password_hash" not in data


def test_signup_with_explicit_username_and_confirmation(client):
    """Test registration providing explicit username and valid password confirmation."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "alpha_trader",
            "display_name": "Alpha Pro Trader",
            "email": "alpha@example.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["username"] == "alpha_trader"
    assert data["display_name"] == "Alpha Pro Trader"
    assert data["email"] == "alpha@example.com"


def test_signup_with_username_only(client):
    """Test registration with username only (display_name defaults to username)."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "quant_wizard",
            "email": "quant@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["username"] == "quant_wizard"
    assert data["display_name"] == "quant_wizard"


def test_signup_password_confirmation_mismatch(client):
    """Test that mismatched password confirmation is rejected with 422 validation error."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "mismatch_user",
            "email": "mismatch@example.com",
            "password": "Password123!",
            "password_confirm": "DifferentPassword123!",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_signup_weak_password(client):
    """Test that password shorter than 8 characters is rejected."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "short_pass",
            "email": "short@example.com",
            "password": "short",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_signup_invalid_email(client):
    """Test that invalid email format is rejected."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "bad_email",
            "email": "not-an-email",
            "password": "Password123!",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_signup_duplicate_email(client, test_user):
    """Test that signing up with an already registered email fails."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": "new_unique_name",
            "email": test_user.email,
            "password": "Password123!",
            "display_name": "Duplicate Email Trader",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "already exists" in response.json()["detail"]


def test_signup_duplicate_username(client, test_user):
    """Test that signing up with an already registered username fails."""
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": test_user.username,
            "email": "brandnew@example.com",
            "password": "Password123!",
            "display_name": "Duplicate Username Trader",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "username already exists" in response.json()["detail"]


def test_login_success_with_email(client, test_user):
    """Test valid credentials using email return access token and set cookies."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "Password123!"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == test_user.email
    assert data["user"]["username"] == test_user.username
    assert "tradezen_access_token" in response.cookies


def test_login_success_with_username(client, test_user):
    """Test valid credentials using username return access token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": test_user.username, "password": "Password123!"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["user"]["username"] == test_user.username


def test_login_wrong_password(client, test_user):
    """Test login with incorrect password is rejected with generic error."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "WrongPassword999!"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid email or password."


def test_login_nonexistent_user(client):
    """Test non-existent user login returns generic message without revealing existence."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody_exists_here@example.com", "password": "Password123!"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid email or password."


def test_get_current_user_profile(client, auth_headers, test_user):
    """Test authenticated access to /auth/me returns standardized user profile."""
    response = client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["email"] == test_user.email
    assert data["username"] == test_user.username
    assert data["display_name"] == test_user.display_name
    assert "password_hash" not in data


def test_unauthenticated_request_rejected(client):
    """Test that protected endpoint fails without token."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_expired_token_rejected(client, test_user):
    """Test that an expired JWT access token is rejected with 401."""
    expired_token = create_access_token(
        subject=str(test_user.id),
        expires_delta=timedelta(seconds=-10),
    )
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Token expired" in response.json()["detail"]


def test_token_refresh(client, test_user):
    """Test that a valid refresh token generates a new access token."""
    refresh_token = create_refresh_token(subject=str(test_user.id))
    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == test_user.email
    assert data["user"]["username"] == test_user.username
    assert "tradezen_access_token" in response.cookies


def test_logout_clears_cookies(client):
    """Test that logout deletes authentication cookies."""
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "Successfully logged out."
