"""Authentication router: signup, login, logout, me."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_current_user,
    check_login_rate_limit,
    record_failed_login,
    clear_failed_logins,
)
from app.core.config import settings
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
)
from app.models.user import User
from app.schemas.auth import UserSignupRequest, UserLoginRequest, UserResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(req: UserSignupRequest, db: Session = Depends(get_db)):
    """Registers a new user account with argon2 password hashing."""
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists.",
        )

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    req: UserLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Logs in an existing user, setting secure cookies and returning token."""
    client_ip = request.client.host if request.client else "unknown"
    check_login_rate_limit(client_ip, req.email)

    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        record_failed_login(client_ip, req.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    clear_failed_logins(client_ip, req.email)

    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    # Set httpOnly secure cookie
    response.set_cookie(
        key="tradezen_access_token",
        value=access_token,
        httponly=True,
        secure=False,  # Set to False in dev to allow local Wi-Fi / HTTP testing
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="tradezen_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
def logout(response: Response):
    """Logs out by clearing authentication cookies."""
    response.delete_cookie(key="tradezen_access_token")
    response.delete_cookie(key="tradezen_refresh_token")
    return {"message": "Successfully logged out."}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Retrieves profile of the currently logged-in user."""
    return current_user
