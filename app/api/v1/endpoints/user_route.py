from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import status 

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.session import get_db
from app.schemas.response_model import ForgotPasswordRequest, LoginRequest, RegisterRequest, ResetPasswordRequest, VerifyOTPRequest
from app.services.database_service import authenticate_user, create_user, get_user_by_email, update_user_otp, update_user_password, verify_user_otp
from app.services.mailing_service import generate_otp, send_password_reset_email

router = APIRouter()

@router.post("/register")
async def register_user(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    user = await create_user(
        db,
        username=payload.name,
        email=payload.email,
        password=payload.password
    )
    return {
        "message": "User registered successfully.",
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at
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
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    user = await authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token(data={"sub": str(user.id)})

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
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=1800  # 30 minutes
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login",status_code=303)
    response.delete_cookie(key="access_token")
    return response

@router.post("/forgot-password")
async def forgot_password_page(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    
    email = payload.email
    
    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    otp= await generate_otp()

    status= await send_password_reset_email(email, user.username, otp)
    if status:
        await update_user_otp(
            db=db,
            user_id=user.id,
            otp=otp
        )
        # Save the OTP to the database (not shown here, but you would typically commit this change)
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
    request: Request,
    otp: VerifyOTPRequest,
    db: AsyncSession = Depends(get_db)
):
    verify = await verify_user_otp(
        db=db,
        email=otp.email,
        otp=otp.otp)
    
    if not verify:
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP"
        )
    
    return JSONResponse(
        content={"message": "OTP verification successfully."},
        status_code=200
    )


@router.post("/reset-password")
async def reset_password(
    request: Request,
    new_password: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    update_password = await update_user_password(db=db, email = new_password.email, new_password=new_password.new_password)
    if not update_password:
        raise HTTPException(
            status_code=400,
            detail="Failed to reset password"
        )
    return JSONResponse(
        content={"message": "Password reset successfully."},
        status_code=200
    )