
from fastapi import APIRouter, HTTPException, Form, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from app.services.chat_services import (
    process_chat,
    get_conversation_history,
    clear_user_history,
    list_pinecone_indexes,
)

router = APIRouter(prefix="/chat", tags=["Chat"])


# ---------- Response Models ----------

class ChatAskResponse(BaseModel):
    answer: str
    username: str
    conversation_id: str
    context_used: bool
    response_time: float


# ---------- Main Endpoints ----------

@router.post("/ask", response_model=ChatAskResponse)
async def chat_ask(
    username: str = Form(..., description="Enter your username"),
    query: str = Form(..., description="Enter your question")
):
    """
    Ask a question. Supports both JSON and HTML form input.
    """
    try:
        resp = await process_chat(username=username, query=query)
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")


@router.get("/history/detailed")
async def chat_history_detailed(
    username: str = Query(..., description="Username to get chat history")
):
    """
    Get detailed conversation history for a user.
    """
    try:
        # Debug: print the received username
        print(f"DEBUG: Received username: {username}")
        history = await get_conversation_history(username)
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get history: {e}")


@router.post("/history/clear")
async def chat_history_clear(
    username: str = Form(..., description="Username to clear history")
):
    """
    Clear all chat history for a user.
    """
    try:
        result = await clear_user_history(username)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear history: {e}")


@router.get("/summary/{username}")
async def chat_summary(username: str):
    """
    Get chat statistics for a user.
    """
    try:
        from app.services.chat_services import get_database_session
        from app.models.models import User, Conversation, Message
        from sqlalchemy import select, func
        
        db = await get_database_session()
        
        try:
            # Get user
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            
            if not user:
                return {
                    "username": username,
                    "total_conversations": 0,
                    "total_messages": 0,
                    "message": "User not found"
                }
            
            # Get stats
            conv_count = await db.execute(
                select(func.count(Conversation.id))
                .where(Conversation.user_id == user.id)
                .where(Conversation.is_deleted == False)
            )
            total_conversations = conv_count.scalar()
            
            msg_count = await db.execute(
                select(func.count(Message.id))
                .join(Conversation)
                .where(Conversation.user_id == user.id)
                .where(Message.is_deleted == False)
            )
            total_messages = msg_count.scalar()
            
            return {
                "username": username,
                "total_conversations": total_conversations,
                "total_messages": total_messages,
                "message": f"User has {total_conversations} conversations with {total_messages} messages"
            }
            
        finally:
            await db.close()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {e}")


@router.get("/indexes")
async def chat_indexes():
    """
    List available Pinecone indexes.
    """
    try:
        indexes = await list_pinecone_indexes()
        return {"available_indexes": indexes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list indexes: {e}")


@router.post("/new-conversation")
async def start_new_conversation(
    username: str = Form(..., description="Username to start new conversation")
):
    """
    Start a new conversation for a user (deactivates current active conversation).
    """
    try:
        from app.services.chat_services import get_database_session
        from app.models.models import User, Conversation
        from sqlalchemy import select, update
        
        db = await get_database_session()
        
        try:
            # Get user
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Deactivate all current active conversations for this user
            await db.execute(
                update(Conversation)
                .where(Conversation.user_id == user.id)
                .where(Conversation.is_active == True)
                .values(is_active=False)
            )
            
            await db.commit()
            
            return {
                "username": username,
                "message": "New conversation started. Previous conversations deactivated."
            }
            
        finally:
            await db.close()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start new conversation: {e}")
