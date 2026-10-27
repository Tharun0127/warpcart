"""Minimal JWT auth for the admin endpoint. One admin user from env vars."""
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

bearer_scheme = HTTPBearer(auto_error=False)


def check_credentials(settings: Settings, username: str, password: str) -> bool:
    # compare_digest avoids leaking how many characters matched via timing.
    user_ok = hmac.compare_digest(username, settings.admin_username)
    password_ok = hmac.compare_digest(password, settings.admin_password)
    return user_ok and password_ok


def create_access_token(settings: Settings, subject: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "role": "admin", "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def require_admin(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
) -> str:
    """Dependency: lets the request through only with a valid admin JWT."""
    settings: Settings = request.app.state.settings
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    if payload.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return payload["sub"]
