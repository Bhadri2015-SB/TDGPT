from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from datetime import datetime
from fastapi import status 

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.session import get_db
from app.schemas.response_model import ForgotPasswordRequest, LoginRequest, RegisterRequest, ResetPasswordRequest, VerifyOTPRequest
from app.services.admin_service import create_admin, authenticate_admin, get_admin_by_email
from app.services.mailing_service import generate_otp, send_password_reset_email

router = APIRouter()

@router.post("/register")
async def register_admin(
    admin_name: str = Form(..., description="Enter your admin name"),
    email: str = Form(..., description="Enter your email"),
    password: str = Form(..., description="Enter your password"),
    db: AsyncSession = Depends(get_db)
):
    admin = await create_admin(
        db,
        admin_name=admin_name,
        email=email,
        password=password
    )
    return {
        "message": "Admin registered successfully.",
        "admin_name": admin.admin_name,
        "email": admin.email,
        "created_at": admin.created_at
    }

@router.get("/login")
async def login_page():
    """
    Render the login page.
    This is a placeholder function. In a real application, you would return an HTML template.
    """
    return JSONResponse(content={"message": "Please provide your login credentials."}, status_code=status.HTTP_200_OK)

@router.post("/login")
async def login(
    email: str = Form(..., description="Enter your email"),
    password: str = Form(..., description="Enter your password"),
    db: AsyncSession = Depends(get_db)
):
    admin = await authenticate_admin(db, email, password)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token(data={"sub": str(admin.id)})

    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer"
        }
    )
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  
        samesite="lax",
        max_age=1800  
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login",status_code=303)
    response.delete_cookie(key="access_token")
    return response

@router.post("/forgot-password")
async def forgot_password_page(
    email: str = Form(..., description="Enter your email"),
    db: AsyncSession = Depends(get_db)
):
    from app.services.mailing_service import generate_otp, send_password_reset_email
    admin = await get_admin_by_email(db, email)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found"
        )
    otp = await generate_otp()
    status = await send_password_reset_email(email, admin.admin_name, otp)
    if status:
        admin.reset_otp = otp
        admin.allow_password_reset = True
        admin.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(admin)
        return JSONResponse(
            content={"message": "OTP sent to your email."},
            status_code=200
        )
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to send OTP"
        )
    

@router.post("/otp-verify")
async def otp_verify(
    email: str = Form(..., description="Enter your email"),
    otp: str = Form(..., description="Enter OTP from email"),
    db: AsyncSession = Depends(get_db)
):
    admin = await get_admin_by_email(db, email)
    if not admin or admin.reset_otp != otp:
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )
    admin.allow_password_reset = True
    admin.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(admin)
    return JSONResponse(
        content={"message": "OTP verification successfully."},
        status_code=200
    )


@router.post("/reset-password")
async def reset_password(
    email: str = Form(..., description="Enter your email"),
    new_password: str = Form(..., description="Enter new password"),
    db: AsyncSession = Depends(get_db)
):
    admin = await get_admin_by_email(db, email)
    if not admin or not admin.allow_password_reset:
        raise HTTPException(
            status_code=400,
            detail="OTP not verified or admin not found"
        )
    from app.core.security import hash_password
    admin.password_hash = await hash_password(new_password)
    admin.allow_password_reset = False
    admin.reset_otp = None
    admin.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(admin)
    return JSONResponse(
        content={"message": "Password reset successfully."},
        status_code=200
    )