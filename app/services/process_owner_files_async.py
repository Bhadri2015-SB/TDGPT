import os
import time
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extractors import PROCESSOR_MAP
from app.utils.file_handler import delete_non_empty_dir, get_file_category, remove_old_folder
from app.utils.file_handler import UPLOAD_ROOT
from app.services.database_service import make_processing, update_db_statuses
from app.vector_db.pinecone_upsert import upsert_documents_to_pinecone

async def process_file(file_path: Path, category: str, user_id: str) -> dict:
    """
    Process a single file and return status dictionary.

    Args:
        file_path (Path): Full path to the uploaded file.
        category (str): File category (e.g., Word, PDF).
        user_id (str): The user's ID.

    Returns:
        dict: File processing result metadata.
    """
    start_time = time.time()
    file_name = file_path.name
    processor = PROCESSOR_MAP.get(category)

    if not processor:
        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "Extraction failed",
            "message": f"No processor available for category: {category}",
            "time_taken_to_process": int(time.time() - start_time)
        }

    try:
        result = await processor(str(file_path))
        total_time = int(float(result.get("total_time_taken", "0").split()[0]))

        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "Processing",
            "message": "Extraction successful. Embedding initiated",
            "time_taken_to_process": total_time or int(time.time() - start_time)
        }

    except Exception as e:
        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "Extraction failed",
            "message": f"Error due to: {str(e)}",
            "time_taken_to_process": int(time.time() - start_time)
        }


async def process_owner_files_async(owner: str, user_id: str, db: AsyncSession):
    """
    Process all files for a given owner, then batch update their statuses in DB.

    Args:
        owner (str): Directory name corresponding to the owner.
        user_id (str): The user's ID.
        db (AsyncSession): Async database session.

    Returns:
        dict: Grouped results by file category.
    """
    owner_dir = UPLOAD_ROOT / owner
    if not owner_dir.exists():
        raise FileNotFoundError("Owner directory not found")

    await make_processing(db, user_id)

    tasks = []
    for category_folder in owner_dir.iterdir():
        if not category_folder.is_dir():
            continue

        category = category_folder.name
        for file_path in category_folder.glob("*"):
            if file_path.is_file():
                tasks.append(process_file(file_path, category, user_id))

    # Wait for all files to be processed concurrently
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # Call to update database
    await update_db_statuses(db, results)
    print("\n-------------------extraction end---------------------------\n")
    


    vector_store=[]
    folder_path = "output"
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        print(f"\n\nProcessing file: {file_path}\n\n")
        if os.path.isfile(file_path):
            #storing in vector db
            vector_store.append(upsert_documents_to_pinecone(file_path,user_id,category,owner))
    print("\n-------------------await start---------------------------\n")
    results = await asyncio.gather(*vector_store, return_exceptions=False)
    await update_db_statuses(db, results)
    # Clean up old folder
    print("\n-------------------stored end---------------------------\n")
    await delete_non_empty_dir('output')
    await remove_old_folder(owner_dir)

    return results





















