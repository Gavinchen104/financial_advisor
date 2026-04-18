"""Authentication: signup, login, logout, /me. Password hashing via bcrypt,
session via JWT in an httpOnly cookie.

Cookie name: `session`. Lifetime: 30 days. JWT signed with SECRET_KEY.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from .db import get_db
from .models import User

_SECRET = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-prod")
_ALGO = "HS256"
_COOKIE = "session"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
_PROD = os.environ.get("ENV", "dev") == "prod"
_MAX_PASSWORD_BYTES = 72  # bcrypt input limit

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- schemas ----------
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str | None

    class Config:
        from_attributes = True


# ---------- helpers ----------
def hash_password(pw: str) -> str:
    # bcrypt only uses the first 72 bytes. Truncate explicitly so long
    # passwords hash deterministically rather than raising.
    pw_bytes = pw.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        pw_bytes = pw.encode("utf-8")[:_MAX_PASSWORD_BYTES]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except Exception:
        return False


def _issue_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=_COOKIE_MAX_AGE)}
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


def _decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGO])
        return int(payload["sub"])
    except Exception:
        return None


def _set_session_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        _COOKIE, token,
        httponly=True, secure=_PROD, samesite="lax",
        max_age=_COOKIE_MAX_AGE, path="/",
    )


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    """FastAPI dependency — requires a valid session cookie, else 401."""
    token = request.cookies.get(_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = _decode_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


def optional_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User | None:
    """Same as current_user, but returns None for anonymous."""
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    uid = _decode_token(token)
    if uid is None:
        return None
    return db.get(User, uid)


# ---------- endpoints ----------
@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, response: Response, db: Annotated[Session, Depends(get_db)]):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(409, "An account with that email already exists.")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=(body.display_name or body.email.split("@")[0]),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, _issue_token(user.id))
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: Annotated[Session, Depends(get_db)]):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    _set_session_cookie(response, _issue_token(user.id))
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]):
    return user
