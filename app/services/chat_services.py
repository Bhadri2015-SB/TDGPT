
import time
from typing import Optional, Dict, Any, List

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.models import User, Conversation, Message
from app.vector_db.pinecone_upsert import (
    get_available_indexes,
    retrival,               
    retrieval_all_admins,   
)
from app.core import config



async def get_database_session() -> AsyncSession:
    """
    Grab a one-off DB session outside FastAPI injection.

    IMPORTANT: Caller must close the returned session.
    """
    async for db in get_db():
        return db


def _ms_since(start: float) -> int:
    return int((time.time() - start) * 1000)


async def _get_active_conversation(db: AsyncSession, user_id: int) -> Optional[Conversation]:
    """
    Return most recent active (non-deleted) conversation for a user.
    """
    res = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .where(Conversation.is_active.is_(True))
        .where(Conversation.is_deleted.is_(False))
        .order_by(desc(Conversation.created_at))
    )
    return res.scalar_one_or_none()



async def process_chat_for_user(
    user: User,
    query: str,
    *,
    use_all_admin_docs: bool = True,
    index_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handle a user query.

    Flow:
      1. Ensure an active conversation (create if needed).
      2. Store the user message.
      3. Retrieve context from document indexes:
         - By default, search *all* admin indexes (use_all_admin_docs=True).
         - Or pass an explicit Pinecone `index_name` to search just one index.
      4. Store the assistant reply.
      5. Return response payload.

    Strict context: if retrieval reports no relevant context, user sees the
    fallback message ("The answer is not available in the provided context.")
    and `context_used` is False.
    """
    start = time.time()
    db = await get_database_session()
    try:
     
        convo = await _get_active_conversation(db, user.id)
        if not convo:
            convo = Conversation(
                user_id=user.id,
                title=query[:50] if len(query) > 50 else query,
                is_active=True,
            )
            db.add(convo)
            await db.flush()  

       
        user_msg = Message(
            conversation_id=convo.id,
            role="user",
            content=query,
        )
        db.add(user_msg)
        await db.flush()

       
        if use_all_admin_docs:
            
            answer_or_error = await retrieval_all_admins(query, db)
        else:
            
            ix = index_name or getattr(config, "MAIN_PINECONE_INDEX", "ss")  
            answer_or_error = await retrival(query, index_name=ix)
            
            

        # Process retrieval response (enhanced format)
        context_used = True
        answer: str
        images: List[Dict] = []
        query_type = "text"
        context_sources = {}

        if isinstance(answer_or_error, dict):
            if "error" in answer_or_error:
                context_used = False
                answer = (
                    f"Sorry {user.username}, I couldn't access the document knowledge base "
                    f"({answer_or_error['error']}). Please try again later."
                )
            else:
                # Enhanced response format
                answer = str(answer_or_error.get("answer", "")).strip()
                images = answer_or_error.get("images", [])
                query_type = answer_or_error.get("query_type", "text")
                context_sources = answer_or_error.get("context_sources", {})
        else:
            answer = str(answer_or_error or "").strip()
            
        if not answer or answer == "The answer is not available in the provided context.":
            context_used = False
            answer = "The answer is not available in the provided context."
        else:
            # Add personalized greeting
            if query_type == "visual" and images:
                answer = f"Hi {user.username}, {answer}\n\nI found {len(images)} relevant image(s) for your visual query."
            else:
                answer = f"Hi {user.username}, {answer}"

        elapsed_ms = _ms_since(start)

    
        asst_msg = Message(
            conversation_id=convo.id,
            role="assistant",
            content=answer,
            context_used=context_used,
            response_time=elapsed_ms,
            model_used="groq-llama3-8b",
            tokens_used=len(answer.split()),
        )
        db.add(asst_msg)

        await db.commit()

        return {
            "answer": answer,
            "images": images, 
            "query_type": query_type,
            "context_sources": context_sources,
            "username": user.username,
            "conversation_id": convo.id,
            "context_used": context_used,
            "response_time": elapsed_ms / 1000.0,
            "message": "OK",
        }

    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()



async def get_conversation_history(username: str) -> Dict[str, Any]:
    """
    Return all (non-deleted) conversations and messages for the given username.
    """
    db = await get_database_session()
    try:
        res = await db.execute(select(User).where(User.username == username))
        user = res.scalar_one_or_none()
        if not user:
            return {
                "username": username,
                "total_conversations": 0,
                "total_message_pairs": 0,
                "conversations": [],
                "message": "User not found",
            }

        convo_q = (
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .where(Conversation.is_deleted.is_(False))
            .options(selectinload(Conversation.messages))
            .order_by(desc(Conversation.created_at))
        )
        convo_res = await db.execute(convo_q)
        convos = convo_res.scalars().all()

        out: List[Dict[str, Any]] = []
        total_pairs = 0

        for c in convos:
            msgs = [m for m in c.messages if not m.is_deleted]
            msgs.sort(key=lambda m: m.created_at)

            formatted = []
            for m in msgs:
                md = {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                if m.role == "assistant":
                    md.update(
                        {
                            "context_used": m.context_used,
                            "response_time_ms": m.response_time,
                            "model_used": m.model_used,
                            "tokens_used": m.tokens_used,
                            "context_sources": m.context_sources,
                            "similarity_scores": m.similarity_scores,
                        }
                    )
                formatted.append(md)

            
            pairs = 0
            for i in range(len(formatted) - 1):
                if formatted[i]["role"] == "user" and formatted[i + 1]["role"] == "assistant":
                    pairs += 1
            total_pairs += pairs

            out.append(
                {
                    "conversation_id": c.id,
                    "title": c.title,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                    "total_messages": len(formatted),
                    "messages": formatted,
                }
            )

        return {
            "username": username,
            "total_conversations": len(out),
            "total_message_pairs": total_pairs,
            "conversations": out,
        }
    finally:
        await db.close()



async def clear_user_history(username: str) -> Dict[str, Any]:
    db = await get_database_session()
    try:
        res = await db.execute(select(User).where(User.username == username))
        user = res.scalar_one_or_none()
        if not user:
            return {"username": username, "cleared_pairs": 0, "message": "User not found."}

        convos_res = await db.execute(select(Conversation).where(Conversation.user_id == user.id))
        convos = convos_res.scalars().all()
        cleared = len(convos)

        for c in convos:
            await db.delete(c)

        await db.commit()
        return {
            "username": username,
            "cleared_pairs": cleared,
            "message": f"Cleared {cleared} conversations.",
        }
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()



async def list_pinecone_indexes() -> List[str]:
    """
    Return list of Pinecone index names (may be empty if helper unavailable).
    """
    try:
        return await get_available_indexes()
    except Exception:
        return []
