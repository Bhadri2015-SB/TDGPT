from pathlib import Path
from app.services.process_owner_files_async import process_owner_files_async
from app.db.session import SessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def start_processing(username: str, user_id: str) -> None:
    """
    Entrypoint to begin asynchronous file processing for a given user.

    Args:
        username (str): Username (folder name / owner of files).
        user_id (str): User's unique ID.

    Raises:
        Exception: Any uncaught exception during processing will be raised after logging.
    """
    try:
        async with SessionLocal() as db:
            await process_owner_files_async(username, user_id, db)
            logger.info(f"[PROCESSING COMPLETE] Files processed for user: {username}")
    except Exception as e:
        logger.error(f"[ERROR] Failed to process files for {username}: {e}")
        raise



