"""Pydantic schemas for authentication and user accounts."""

import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class UserSignupRequest(BaseModel):
    """Schema for user registration supporting username, display name, and password confirmation."""
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    password_confirm: Optional[str] = Field(None, min_length=8, description="Password confirmation if provided")
    username: Optional[str] = Field(None, min_length=3, max_length=50, description="Unique username handle")
    display_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Full or display name")

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("username")
    @classmethod
    def validate_and_normalize_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.lower().strip()
        if not re.match(r"^[a-z0-9_-]{3,50}$", v):
            raise ValueError("Username must be 3-50 characters containing only letters, numbers, underscores, or hyphens.")
        return v

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = " ".join(v.split()).strip()
        if len(cleaned) < 2 or len(cleaned) > 100:
            raise ValueError("Display name must be between 2 and 100 characters.")
        return cleaned

    @model_validator(mode="after")
    def validate_and_cross_fill_identity(self) -> "UserSignupRequest":
        # Validate password confirmation if present
        if self.password_confirm is not None and self.password != self.password_confirm:
            raise ValueError("Password confirmation does not match password.")

        # Ensure either username or display_name is present and cross-populate
        if not self.username and not self.display_name:
            # Fall back to email prefix
            prefix = self.email.split("@")[0]
            sanitized = re.sub(r"[^a-z0-9_-]", "_", prefix.lower()).strip("_")
            self.username = (sanitized[:50] if len(sanitized) >= 3 else f"user_{sanitized}")[:50]
            self.display_name = prefix

        elif self.username and not self.display_name:
            self.display_name = self.username

        elif self.display_name and not self.username:
            sanitized = re.sub(r"[^a-z0-9_-]", "_", self.display_name.lower()).strip("_")
            if len(sanitized) < 3:
                sanitized = re.sub(r"[^a-z0-9_-]", "_", self.email.split("@")[0].lower()).strip("_")
            if len(sanitized) < 3:
                sanitized = f"trader_{sanitized}"
            self.username = sanitized[:50]

        return self


class UserLoginRequest(BaseModel):
    """Schema for user login accepting either email or username."""
    email: Optional[str] = None
    username: Optional[str] = None
    password: str = Field(..., min_length=1)

    @field_validator("email", "username")
    @classmethod
    def normalize_identifier(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return v.lower().strip()
        return None

    @model_validator(mode="after")
    def validate_identifier_provided(self) -> "UserLoginRequest":
        if not self.email and not self.username:
            raise ValueError("Either email or username must be provided for login.")
        return self


class UserResponse(BaseModel):
    """User profile response schema with standardized identity fields."""
    id: int
    username: str
    email: EmailStr
    display_name: str
    is_active: bool
    current_season: int = 1
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token response schema."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
