from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from vigil.core.auth import create_admin_token, verify_password
from vigil.core.config import get_settings

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    s = get_settings()
    if not (
        verify_password(body.username, s.admin_username)
        and verify_password(body.password, s.admin_password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")
    return LoginResponse(access_token=create_admin_token(body.username))
