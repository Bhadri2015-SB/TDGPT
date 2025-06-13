import time
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extractors import PROCESSOR_MAP
from app.utils.file_handler import get_file_category, remove_old_folder
from app.utils.file_handler import UPLOAD_ROOT
from app.services.database_service import update_db_statuses

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
            "status": "extraction failed",
            "message": f"No processor available for category: {category}",
            "time_taken_to_process": int(time.time() - start_time)
        }

    try:
        result = await processor(str(file_path))
        total_time = int(float(result.get("total_time_taken", "0").split()[0]))

        return {
            "user_id": user_id,
            "file_name": file_name,
            "status": "processed",
            "message": "Process success",
            "time_taken_to_process": total_time or int(time.time() - start_time)
        }

    except Exception as e:
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

    # Clean up old folder
    await remove_old_folder(owner_dir)
    print("\n-------------------end---------------------------\n")
    return results
























# import asyncio
# from pathlib import Path
# from app.utils.file_handler import change_to_processed, get_file_category, remove_old_folder
# from app.services.extractors import PROCESSOR_MAP
# from app.utils.file_handler import UPLOAD_ROOT
# import inspect


# async def process_file(file_path: Path, category: str):
#     try:
#         processor = PROCESSOR_MAP.get(category)
#         if processor:
#             # if inspect.iscoroutinefunction(processor):
#                 # If the processor is an async function
#             print(f"Processing file asynchronously:{processor}")
#             result = await processor(str(file_path))
#             # else:
#             #     # If the processor is a sync function
#             #     print("Processing file synchronously")
#             #     loop = asyncio.get_event_loop()
#             #     result = await loop.run_in_executor(None, processor, str(file_path))
#             # loop = asyncio.get_event_loop()
#             # result = await loop.run_in_executor(None, processor, str(file_path))
#             # await change_to_processed(file_path.parent.parent.name, str(file_path), category)
#             return {"file": file_path.name, "output": result}
#         else:
#             return {"file": file_path.name, "error": f"No processor for category {category}"}
#     except Exception as e:
#         return {"file": file_path.name, "error": str(e)}

# async def process_owner_files_async(owner: str):
#     owner_dir = UPLOAD_ROOT / owner
#     # print(f"Processing files for owner: {owner}, {owner_dir}")
#     if not owner_dir.exists():
#         raise FileNotFoundError("Owner directory not found")

#     tasks = []
#     for category_folder in owner_dir.iterdir():
#         # print(f"Processing category: {category_folder}, {category_folder.name}")
#         if not category_folder.is_dir():
#             continue
#         category = category_folder.name
#         for file_path in category_folder.glob("*"):
#             # print(f"Processing file: {file_path}, Category: {category}")
#             if file_path.is_file():
#                 tasks.append(process_file(file_path, category))

#     results = await asyncio.gather(*tasks)
#     await remove_old_folder(owner_dir)

#     grouped = {}
#     for item in results:
#         ext = Path(item["file"]).suffix.lower()
#         cat = await get_file_category(ext)
#         grouped.setdefault(cat, []).append(item)
#     return grouped

