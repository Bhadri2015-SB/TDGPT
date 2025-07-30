

from fastapi import APIRouter, HTTPException, Depends, Response
from datetime import timedelta
from typing import Optional
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.models import User
from app.services.user_service import (
    create_user,
    authenticate_user,       
    send_otp_to_email,
    verify_otp_code,
    reset_user_password,
)
from app.core.security import create_access_token, verify_password

router = APIRouter(tags=["user"])



ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour



class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str



@router.post("/register")
async def register_user(
    user: UserRegister,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user.
    """
    created_user = await create_user(db, user.username, user.email, user.password)
    if created_user is None:
        raise HTTPException(status_code=400, detail="User already exists.")
    return {
        "id": created_user.id,
        "username": created_user.username,
        "email": created_user.email,
        "message": "User registered successfully.",
    }



@router.post("/login", response_model=Token)
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    
 
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    
    if not await verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect password.")

    
    expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(data={"sub": str(user.id)}, expires_delta=expires)

   
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,  
        samesite="lax",
        max_age=int(expires.total_seconds()),
    )

    return Token(access_token=token)



@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    sent = await send_otp_to_email(db, payload.email)
    if not sent:
        raise HTTPException(status_code=404, detail="Email not found.")
    return {"message": "OTP sent to your email."}



@router.post("/verify-otp")
async def verify_otp(
    payload: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    ok = await verify_otp_code(db, payload.email, payload.otp)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")
    return {"message": "OTP verified successfully."}



@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    ok = await reset_user_password(db, payload.email, payload.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found or OTP not verified.")
    return {"message": "Password reset successfully."}



@router.post("/logout")
async def logout(response: Response):
    """
    Stateless JWT logout: client should discard token.
    We clear our optional cookie for browser clients.
    """
    response.delete_cookie("access_token")
    return {"message": "Logged out. Discard your token on the client side."}
