"""Pydantic schemas for authentication and user accounts."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserSignupRequest(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    display_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower().strip()


class UserLoginRequest(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower().strip()


class UserResponse(BaseModel):
    """User profile response schema."""
    id: int
    email: EmailStr
    display_name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token response schema."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
