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


# Optional Celery-compatible sync wrapper (if using Celery)
# from celery import shared_task

# @shared_task
# def process_owner_files_task(username: str, user_id: str):
#     """
#     Celery-compatible sync wrapper for async processing.
#     Used if integrating with a task queue like Celery.
#     """
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)

#     async def runner():
#         async with SessionLocal() as db:
#             await process_owner_files_async(username, user_id, db)

#     try:
#         loop.run_until_complete(runner())
#     finally:
#         loop.close()
