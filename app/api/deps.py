"""FastAPI request dependencies, authentication, and login rate limiting."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

security_scheme = HTTPBearer(auto_error=False)

# In-memory login failure tracker: key -> list of failure timestamps
# Key format: f"{ip}:{email}"
_failed_login_attempts: Dict[str, List[datetime]] = {}
RATE_LIMIT_WINDOW_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5


def check_login_rate_limit(ip: str, email: str) -> None:
    """Enforces 5 failed tries per 15 min per IP and email."""
    key = f"{ip}:{email.lower().strip()}"
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    
    # Prune expired timestamps
    attempts = [t for t in _failed_login_attempts.get(key, []) if t > cutoff]
    _failed_login_attempts[key] = attempts

    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes.",
        )


def record_failed_login(ip: str, email: str) -> None:
    """Records a failed login attempt."""
    key = f"{ip}:{email.lower().strip()}"
    now = datetime.now(timezone.utc)
    if key not in _failed_login_attempts:
        _failed_login_attempts[key] = []
    _failed_login_attempts[key].append(now)


def clear_failed_logins(ip: str, email: str) -> None:
    """Clears failed login attempts upon successful authentication."""
    key = f"{ip}:{email.lower().strip()}"
    _failed_login_attempts.pop(key, None)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Extracts and verifies authenticated user from Authorization header or cookie."""
    token: Optional[str] = None

    if credentials:
        token = credentials.credentials
    else:
        # Check httpOnly cookie
        token = request.cookies.get("tradezen_access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        token_type = payload.get("type")
        if not user_id or token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token claims",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user
