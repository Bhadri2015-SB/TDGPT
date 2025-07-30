from fastapi import APIRouter, HTTPException, Form, Depends
from pydantic import BaseModel

from app.core.security import get_current_user
from app.models.models import User
from app.services.chat_services import (
    process_chat_for_user,
    get_conversation_history,
    clear_user_history,
    list_pinecone_indexes,
)

router = APIRouter(prefix="/chat", tags=["user"])


class ChatAskResponse(BaseModel):
    answer: str
    username: str
    conversation_id: int | None
    context_used: bool
    response_time: float


@router.post("/ask", response_model=ChatAskResponse)
async def chat_ask(
    query: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    
    try:
        resp = await process_chat_for_user(current_user, query, use_all_admin_docs=True)
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")


@router.get("/history/detailed")
async def chat_history_detailed(current_user: User = Depends(get_current_user)):
    """
    Fetch the detailed conversation history for the current user.
    """
    try:
        history = await get_conversation_history(current_user.username)
        history["username"] = current_user.username
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get history: {e}")


@router.post("/history/clear")
async def chat_history_clear(current_user: User = Depends(get_current_user)):
    """
    Clear all chat history for the current user.
    """
    try:
        result = await clear_user_history(current_user.username)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear history: {e}")


@router.get("/summary")
async def chat_summary(current_user: User = Depends(get_current_user)):
    """
    Return chat summary (total conversations & message pairs).
    """
    try:
        history = await get_conversation_history(current_user.username)
        return {
            "username": current_user.username,
            "total_conversations": history.get("total_conversations", 0),
            "total_message_pairs": history.get("total_message_pairs", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {e}")


@router.get("/indexes")
async def chat_indexes():
    """
    List all available Pinecone indexes.
    """
    try:
        return {"available_indexes": await list_pinecone_indexes()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list indexes: {e}")
