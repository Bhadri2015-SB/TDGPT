from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import status 

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.session import get_db
from app.services.database_service import authenticate_user, create_user

router = APIRouter()

@router.post("/register")
async def register_user(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    
    user = await create_user(db, username=name, email=email, password=password)
    return {"message": "User registered successfully.", "username": user.username, "email": user.email ,"created_at": user.created_at}

@router.get("/login")
async def login_page():
    """
    Render the login page.
    This is a placeholder function. In a real application, you would return an HTML template.
    """
    return JSONResponse(content={"message": "Please provide your login credentials."}, status_code=status.HTTP_200_OK)

@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    user = await authenticate_user(db, email, password)
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