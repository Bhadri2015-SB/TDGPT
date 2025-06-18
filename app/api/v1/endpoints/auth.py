from fastapi import APIRouter, Form, HTTPException

router = APIRouter()

@router.post("/token")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == "testuser" and password == "testpass":
        return {
            "access_token": "fake-jwt-token",
            "token_type": "bearer"
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")
