

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from grpc import Status
from requests import Session

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.session import get_db
from app.services.database_service import authenticate_user, create_user


router = APIRouter()

@router.post("/register")
async def register_user(name: str = Form(...), email: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await create_user(db, username=name, email=email, password=password)
    return user

@router.post("/login")
async def login(request:Request, email:str=Form(...),password:str=Form(...), db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, email, password)
    if not user:
        raise HTTPException(
            status_code=Status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    access_token = await create_access_token(data={"sub": str(user.id)})
    # return {"access_token": access_token, "token_type": "bearer"}
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
        secure=False,  # Set True in production with HTTPS
        samesite="lax",
        max_age=1800  # 30 minutes
    )
    return response