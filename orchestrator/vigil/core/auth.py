import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.core.config import get_settings
from vigil.db.models import Observer
from vigil.db.session import get_db

_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


# ---- API keys (agents) -------------------------------------------------------
# Key format: "vg_<observer_uuid_hex>_<secret>" — the uuid lets us look up the
# row directly instead of argon2-verifying against every observer.

def generate_api_key(observer_id: uuid.UUID) -> tuple[str, str]:
    """Return (plaintext_key, argon2_hash). Plaintext is shown exactly once."""
    secret = secrets.token_urlsafe(32)
    key = f"vg_{observer_id.hex}_{secret}"
    return key, _hasher.hash(secret)


def _parse_api_key(key: str) -> tuple[uuid.UUID, str] | None:
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != "vg":
        return None
    try:
        return uuid.UUID(hex=parts[1]), parts[2]
    except ValueError:
        return None


async def require_agent(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Observer:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    parsed = _parse_api_key(creds.credentials)
    if parsed is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed API key")
    observer_id, secret = parsed
    observer = await db.get(Observer, observer_id)
    if observer is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown observer")
    try:
        _hasher.verify(observer.api_key_hash, secret)
    except VerifyMismatchError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key") from e
    return observer


# ---- Admin JWT ---------------------------------------------------------------

def create_admin_token(username: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": username, "role": "admin", "iat": now, "exp": now + timedelta(hours=s.jwt_ttl_hours)},
        s.jwt_secret,
        algorithm="HS256",
    )


def verify_admin_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from e
    if payload.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not an admin token")
    return payload


async def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    return verify_admin_token(creds.credentials)


async def require_admin_ws(websocket: WebSocket) -> dict:
    """WebSocket auth: ?token=<jwt> query param."""
    token = websocket.query_params.get("token", "")
    try:
        return verify_admin_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        raise


def verify_password(plain: str, expected: str) -> bool:
    return secrets.compare_digest(plain, expected)
