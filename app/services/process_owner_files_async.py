import time
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extractors import PROCESSOR_MAP
from app.utils.file_handler import get_file_category, remove_old_folder
from app.utils.file_handler import UPLOAD_ROOT
from app.services.database_service import update_db_statuses
from app.core.logger import app_logger  


async def process_file(file_path: Path, category: str, user_id: str) -> dict:
    """
    Process a single file and return status dictionary.
    """
    start_time = time.time()
    file_name = file_path.name
    processor = PROCESSOR_MAP.get(category)

    app_logger.debug(f"Processing file: {file_path} [category: {category}]")

    if not processor:
        app_logger.warning(f"No processor found for category '{category}'")
        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "extraction failed",
            "message": f"No processor available for category: {category}",
            "time_taken_to_process": int(time.time() - start_time)
        }

    try:
        result = await processor(str(file_path))
        total_time = int(float(result.get("total_time_taken", "0").split()[0]))

        app_logger.info(f"Successfully processed {file_name} in {total_time} seconds.")
        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "processed",
            "message": "Process success",
            "time_taken_to_process": total_time or int(time.time() - start_time)
        }

    except Exception as e:
        app_logger.exception(f"Error processing file {file_name}: {e}")
        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "extraction failed",
            "message": str(e),
            "time_taken_to_process": int(time.time() - start_time)
        }


async def process_owner_files_async(owner: str, user_id: str, db: AsyncSession):
    """
    Process all files for a given owner, then batch update their statuses in DB.
    """
    owner_dir = UPLOAD_ROOT / owner

    if not owner_dir.exists():
        app_logger.error(f"Owner directory not found: {owner_dir}")
        raise FileNotFoundError("Owner directory not found")

    app_logger.info(f"Starting processing for owner: {owner}, user: {user_id}")

    tasks = []
    for category_folder in owner_dir.iterdir():
        if not category_folder.is_dir():
            continue

        category = category_folder.name
        for file_path in category_folder.glob("*"):
            if file_path.is_file():
                tasks.append(process_file(file_path, category, user_id))

    results = await asyncio.gather(*tasks, return_exceptions=False)

    app_logger.debug(f"Finished processing {len(results)} file(s). Updating DB...")

    await update_db_statuses(db, results)

    await remove_old_folder(owner_dir)
    app_logger.info(f"Cleaned up folder: {owner_dir}")
    app_logger.info("File processing completed.\n")

    return results
