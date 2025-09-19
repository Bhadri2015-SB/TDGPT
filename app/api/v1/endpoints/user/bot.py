import uuid
import os
import re
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Header
from pydantic import BaseModel, validator
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.models import BotSession, User
from app.services.user_service import create_user

from app.services.groq_client import chat_complete
from app.vector_db.pinecone_upsert import retrieval_all_admins
from app.core import config

router = APIRouter(prefix="/bot", tags=["user"])


async def get_session_by_token(db: AsyncSession, token: str) -> Optional[BotSession]:
    result = await db.execute(select(BotSession).where(BotSession.session_token == token))
    return result.scalar_one_or_none()

def gatekeeper(session: Optional[BotSession]):
    if not session or not session.collected_name:
        return {"ask": "What's your name?"}
    if not session.collected_phone_number:
        return {"ask": "What's your phone number?"}
    if session.state != "ready":
        return {"ask": "Please complete name and phone number first."}
    return None

def _resolve_session_token(request: Request, payload_token: Optional[str], x_session_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if payload_token:
        if payload_token.strip():
            return payload_token.strip()
    if x_session_token:
        if x_session_token.strip():
            return x_session_token.strip()
    if authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            t = auth[7:].strip()
            if t:
                return t
    cookie_token = request.cookies.get("session_token")
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()
    return None


@router.post("/start")
async def start_bot(response: Response, db: AsyncSession = Depends(get_db)):
    token = str(uuid.uuid4())
    session = BotSession(session_token=token, state="ask_name")
    db.add(session)
    await db.commit()
    await db.refresh(session)

   
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60*60*24*7,
        path="/",
    )

    return {
        "session_token": token,
        "message": "Welcome to Troudz Assistant!",
        "ask": "What's your name?"
    }


class NamePayload(BaseModel):
    name: str

@router.post("/name")
async def submit_name(
    payload: NamePayload,
    request: Request,
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db)
):
    token = _resolve_session_token(request, None, x_session_token, authorization)
    session = await get_session_by_token(db, token) if token else None
    if not session:
        return {"message": "Session expired or invalid. Please restart.", "ask": "What's your name?"}

    name_val = payload.name.strip()
    invalid = ["string","your name","name","null","none","test","user","example"]
    if not name_val or name_val.lower() in invalid or len(name_val) < 2:
        raise HTTPException(status_code=400, detail="Please provide a valid name")

    session.collected_name = name_val
    session.state = "ask_phone"
    await db.commit()
    return {"message": f"Hi {name_val}!", "ask": "What's your phone number?"}

class PhoneNumberPayload(BaseModel):
    phone_number: str
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        # Remove any spaces or special characters
        cleaned = re.sub(r'[^0-9]', '', v)
        
        # Check if exactly 10 digits
        if len(cleaned) != 10:
            raise ValueError('Phone number must be exactly 10 digits')
        
        # Check if all characters are digits
        if not cleaned.isdigit():
            raise ValueError('Phone number must contain only digits')
            
        return cleaned

@router.post("/phone")
async def submit_phone_number(
    payload: PhoneNumberPayload,
    request: Request,
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db)
):
    token = _resolve_session_token(request, None, x_session_token, authorization)
    session = await get_session_by_token(db, token) if token else None
    if not session or not session.collected_name:
        return {"message": "Please provide your name first!", "ask": "What's your name?"}

    phone_val = payload.phone_number
    invalid = ["1234567890", "0000000000", "1111111111", "2222222222", "3333333333", "4444444444", "5555555555", "6666666666", "7777777777", "8888888888", "9999999999"]
    if phone_val in invalid:
        raise HTTPException(status_code=400, detail="Please provide a valid phone number")

    session.collected_phone_number = phone_val
    session.state = "ready"

    user_result = await db.execute(select(User).where(User.phone_number == phone_val))
    user = user_result.scalar_one_or_none()
    if not user:
        user = await create_user(db, username=session.collected_name, phone_number=phone_val, password="TempPass#123")
    else:
        user.username = session.collected_name
    session.user_id = user.id
    await db.commit()

    return {"message": f"Thank you {session.collected_name}! Now you can ask me anything."}


class QueryPayload(BaseModel):
    query: str

@router.post("/message")
async def message(
    payload: QueryPayload,
    request: Request,
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db)
):
    token = _resolve_session_token(request, None, x_session_token, authorization)
    session = await get_session_by_token(db, token) if token else None
    gate = gatekeeper(session)
    if gate:
        return gate

    
    result = await retrieval_all_admins(payload.query, db, admin_name=config.DEFAULT_ADMIN_NAME)
    if isinstance(result, dict):
        return {"query": payload.query, "response": result}
   
    return {"query": payload.query, "response": {"answer": result, "images": [], "query_type": "text"}}

class OtherQueryPayload(BaseModel):
    query: str

@router.post("/other-queries")
async def other_queries(
    payload: OtherQueryPayload,
    request: Request,
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db)
):
    token = _resolve_session_token(request, None, x_session_token, authorization)
    session = await get_session_by_token(db, token) if token else None
    gate = gatekeeper(session)
    if gate:
        return gate

    system_msg = "You are a helpful assistant. Answer clearly."
    final_answer = chat_complete(system=system_msg, user=payload.query)
    return {"answer": final_answer}