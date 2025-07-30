from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import User, Admin
import app.core.config as settings



oauth2_user_scheme = OAuth2PasswordBearer(tokenUrl="/user/auth/login")
oauth2_admin_scheme = OAuth2PasswordBearer(tokenUrl="/admin/auth/login")



SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES)



def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Sign and return a JWT. Caller MUST include an identifier in data['sub'].
    Recommended: use the database primary key (string).
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _extract_bearer_token(request: Request) -> str:
    """
    Pull Bearer token from Authorization header; fallback to 'access_token' cookie.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, param = get_authorization_scheme_param(auth_header)
        if scheme.lower() == "bearer" and param:
            return param

    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )



async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """
    Resolve the authenticated *User* from the request's JWT.
    Expects token 'sub' to hold the *User.id* (string or int convertible).
    """
    token = _extract_bearer_token(request)
    payload = decode_token(token)

    sub_val = payload.get("sub")
    if sub_val is None:
        raise HTTPException(status_code=401, detail="Invalid token payload (missing sub).")

   
    try:
        sub_val_int = int(sub_val)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Token subject invalid for user lookup.")

    result = await db.execute(select(User).where(User.id == sub_val_int))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def get_current_admin(request: Request, db: AsyncSession = Depends(get_db)) -> Admin:
    """
    Resolve the authenticated *Admin* from the request's JWT.
    Expects token 'sub' to hold the *Admin.id* (UUID string).
    """
    token = _extract_bearer_token(request)
    payload = decode_token(token)

    admin_id = payload.get("sub")
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload (missing sub).")

    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=401, detail="Admin not found")

    return admin



async def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False
