
import time
import uuid
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from app.db.session import get_db
from app.models.models import User, Conversation, Message
from app.vector_db.pinecone_upsert import retrival  # existing retrieval -> LLM answer
try:
    from app.vector_db.pinecone_upsert import get_available_indexes  # if you add helper
except ImportError:
    get_available_indexes = None

# ------------------------------------------------------------------
# Database-based conversation storage
# ------------------------------------------------------------------

async def get_database_session() -> AsyncSession:
    """Get database session for database operations."""
    async for db in get_db():
        return db

async def get_or_create_user(db: AsyncSession, username: str) -> User:
    """Get existing user or create new one."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            username=username,
            email=f"{username}@temp.com",  # Temporary email
            password_hash="temp_hash"  # Temporary password hash
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    return user


def _now() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_now()))


async def list_pinecone_indexes() -> List[str]:
    if get_available_indexes is None:
        # Fallback: no helper available
        return []
    return await get_available_indexes()


async def process_chat(
    username: str,
    query: str,
) -> Dict[str, Any]:
    """
    Main chat call: retrieve context, get LLM answer, persist pair in database.
    Uses username as the index name.
    Ensures proper user → assistant message sequence.
    """
    start = _now()
    
    db = await get_database_session()
    
    try:
        # Get or create user
        user = await get_or_create_user(db, username)
        
        # Get the most recent active conversation for this user
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .where(Conversation.is_active == True)
            .where(Conversation.is_deleted == False)
            .order_by(desc(Conversation.created_at))
        )
        conversation = result.scalar_one_or_none()
        
        # If no active conversation exists, create a new one
        if not conversation:
            conversation = Conversation(
                user_id=user.id,
                title=query[:50] + "..." if len(query) > 50 else query,
                is_active=True
            )
            db.add(conversation)
            await db.flush()  # Get the conversation ID without committing
        
        # Check if the last message in this conversation is from the user
        # If it is, we need to ensure we don't have duplicate user messages
        last_message_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .where(Message.is_deleted == False)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        last_message = last_message_result.scalar_one_or_none()
        
        # Only add user message if:
        # 1. There are no messages in this conversation, OR
        # 2. The last message is from the assistant (proper alternation)
        should_add_user_message = (
            last_message is None or 
            last_message.role == "assistant"
        )
        
        if should_add_user_message:
            # Add user message to the conversation
            user_message = Message(
                conversation_id=conversation.id,
                role="user",
                content=query
            )
            db.add(user_message)
            await db.flush()  # Flush to get the ID but don't commit yet
            
            # Use username as index name for retrieval
            answer_or_error = await retrival(query, index_name=username)
            
            # Determine if we got a valid answer or an error payload
            context_used = True
            answer: str
            
            if isinstance(answer_or_error, dict) and "error" in answer_or_error:
                # Retrieval failed
                context_used = False
                answer = (
                    f"Context retrieval failed ({answer_or_error['error']}). "
                    "Please check that your documents are processed and the index exists."
                )
            else:
                # Many of your current retrival() calls return a string (LLM text)
                # but we still guard in case None
                answer = str(answer_or_error) if answer_or_error is not None else ""
                if not answer.strip():
                    context_used = False
                    answer = (
                        "I could not find relevant context in your knowledge base. "
                        "Upload documents or try a different question."
                    )
            
            response_time = round((_now() - start) * 1000)  # Convert to milliseconds
            
            # Add assistant message immediately after user message (same transaction)
            assistant_message = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
                context_used=context_used,
                response_time=response_time,
                model_used="groq-llama3-8b",
                tokens_used=len(answer.split()) if answer else 0
            )
            db.add(assistant_message)
            
            # Commit both messages together to ensure proper sequence
            await db.commit()
            
            return {
                "answer": answer,
                "username": username,
                "conversation_id": conversation.id,
                "context_used": context_used,
                "response_time": response_time / 1000,  # Convert back to seconds for API response
                "message": "New user-assistant pair created"
            }
        else:
            # The last message is from the user, so we should not add another user message
            # This prevents duplicate user messages and ensures proper alternation
            return {
                "answer": f"Error: The last message in this conversation is already from the user. Expected assistant response first.",
                "username": username,
                "conversation_id": conversation.id,
                "context_used": False,
                "response_time": 0,
                "message": "Prevented duplicate user message - conversation flow maintained"
            }
    
    except Exception as e:
        await db.rollback()
        raise e
    finally:
        await db.close()


async def get_conversation_history(username: str) -> Dict[str, Any]:
    """
    Return detailed conversation history for a user from database.
    All conversations with messages, newest first.
    """
    # Debug: print the received username
    print(f"DEBUG get_conversation_history: Received username: '{username}'")
    
    db = await get_database_session()
    
    try:
        # Get user
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        
        if not user:
            return {
                "username": username,
                "total_conversations": 0,
                "conversations": [],
                "total_message_pairs": 0,
                "message": "User not found"
            }
        
        # Get all conversations with messages
        query = (
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .where(Conversation.is_deleted == False)
            .options(selectinload(Conversation.messages))
            .order_by(desc(Conversation.created_at))
        )
        
        result = await db.execute(query)
        conversations = result.scalars().all()
        
        formatted_conversations = []
        total_message_pairs = 0
        
        for conversation in conversations:
            # Sort messages by creation time
            messages = sorted(
                [msg for msg in conversation.messages if not msg.is_deleted], 
                key=lambda m: m.created_at
            )
            
            # Format messages and ensure proper user → assistant pairing
            formatted_messages = []
            current_pair_count = 0
            
            for i, msg in enumerate(messages):
                message_data = {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "created_at": msg.created_at.isoformat()
                }
                
                # Add extra data for assistant messages
                if msg.role == "assistant":
                    message_data.update({
                        "context_used": msg.context_used,
                        "response_time_ms": msg.response_time if msg.response_time else 0,
                        "response_time_seconds": (msg.response_time / 1000) if msg.response_time else 0,
                        "model_used": msg.model_used,
                        "tokens_used": msg.tokens_used,
                        "context_sources": msg.context_sources,
                        "similarity_scores": msg.similarity_scores
                    })
                
                formatted_messages.append(message_data)
            
            # Count proper user → assistant pairs
            for i in range(len(formatted_messages) - 1):
                if (formatted_messages[i]["role"] == "user" and 
                    formatted_messages[i + 1]["role"] == "assistant"):
                    current_pair_count += 1
            
            total_message_pairs += current_pair_count
            
            # Format conversation
            conversation_data = {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "is_active": conversation.is_active,
                "created_at": conversation.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": conversation.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                "created_at_iso": conversation.created_at.isoformat(),
                "updated_at_iso": conversation.updated_at.isoformat(),
                "total_messages": len(formatted_messages),
                "messages": formatted_messages
            }
            
            formatted_conversations.append(conversation_data)
        
        return {
            "username": username,
            "total_conversations": len(formatted_conversations),
            "conversations": formatted_conversations,
            "total_message_pairs": total_message_pairs,
            "message": f"Found {len(formatted_conversations)} conversations with {total_message_pairs} message pairs"
        }
    
    except Exception as e:
        raise e
    finally:
        await db.close()


async def clear_user_history(username: str) -> Dict[str, Any]:
    """
    Remove all conversations and messages for a user from database.
    """
    db = await get_database_session()
    
    try:
        # Get user
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        
        if not user:
            return {
                "username": username,
                "cleared_pairs": 0,
                "message": "User not found, no pairs to clear.",
            }
        
        # Get count of conversations before deleting
        count_result = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
        )
        cleared_count = count_result.scalar()
        
        # Delete all conversations (cascade will delete messages)
        conversations_result = await db.execute(
            select(Conversation).where(Conversation.user_id == user.id)
        )
        for conv in conversations_result.scalars().all():
            await db.delete(conv)
        
        await db.commit()
        
        return {
            "username": username,
            "cleared_pairs": cleared_count,
            "message": f"Cleared {cleared_count} conversations with message pairs.",
        }
    
    except Exception as e:
        await db.rollback()
        raise e
    finally:
        await db.close()
