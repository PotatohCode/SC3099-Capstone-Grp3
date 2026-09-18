"""
Password hashing and JWT encode/decode.

Token structure follows SECURITY-REQUIREMENTS.md's "Token Structure" exactly
(sub/email/role/exp/iat), plus a `type` claim (access|refresh) so /auth/refresh
can reject an access token used where a refresh token is expected, and vice
versa - the spec doesn't forbid extra claims, and tokens never carry anything
sensitive beyond what's already in the public API responses.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS
)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(
    subject: str, email: str, role: str, token_type: Literal["access", "refresh"], expires_delta: timedelta
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "email": email,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, email: str, role: str) -> str:
    return _create_token(
        user_id, email, role, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: str, email: str, role: str) -> str:
    return _create_token(
        user_id, email, role, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str) -> dict[str, Any]:
    """Raises jose.JWTError (including ExpiredSignatureError) if invalid/expired."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
