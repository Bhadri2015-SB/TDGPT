"""
High-level async pipeline to extract -> embed -> update DB for all files
uploaded by an Admin (owner folder under UPLOAD_ROOT).

PHASES
------
1. Mark eligible UploadRecord rows "processing".
2. Create Document rows (processing state).
3. Run extractors in parallel (PROCESSOR_MAP).
4. Update UploadRecords to "Processing" (extraction done; embedding next).
5. Run Pinecone upsert in parallel.
6. Update UploadRecords & Document rows to "Processed" / "Embedding failed".
7. Cleanup temp output folders.

REQUIRED STATUS DICT SHAPE (passed to DB updaters)
---------------------------------------------------
{
    "admin_id": <admin UUID>,
    "file_name": <original filename as uploaded>,
    "status": <"Processing" | "Processed" | "Extraction failed" | "Embedding failed"...>,
    "message": <human readable>,
    "time_taken_to_process": <int seconds>   # optional, safe to omit/None
}
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import OUTPUT_DIRECTORY,IMAGE_OUTPUT_DIR
from app.services.extractors import PROCESSOR_MAP
from app.utils.file_handler import (
    UPLOAD_ROOT,
    delete_non_empty_dir,
    remove_old_folder,
)
from app.vector_db.pinecone_upsert import upsert_documents_to_pinecone, _clean_name
from app.vector_db.upsert_image import upsert_image_folder
from app.services.database_service import (
    make_processing,
    update_db_statuses,
)



async def process_file(file_path: Path, category: str, admin_id: str) -> Dict:
    """
    Run category-specific extractor. Extractor is expected to create a JSON
    representation in the global `output/` directory (downstream embedding reads it).

    On success -> status="Processing" (extraction complete; embedding next).
    On failure -> status="Extraction failed".
    """
    start = time.time()
    processor = PROCESSOR_MAP.get(category)
    file_name = file_path.name

    if not processor:
        return {
            "admin_id": admin_id,
            "file_name": file_name,
            "status": "Extraction failed",
            "message": f"No extractor for category {category}.",
            "time_taken_to_process": int(time.time() - start),
        }

    try:
        result = await processor(str(file_path))

    
        total_time = None
        for key in ("total_time_taken", "total_time", "time_taken"):
            if key in result:
                try:
                    total_time = int(float(str(result[key]).split()[0]))
                except Exception:
                    pass
                break
        if total_time is None:
            total_time = int(time.time() - start)

        return {
            "admin_id": admin_id,
            "file_name": file_name,
            "status": "Processing",  
            "message": "Extraction successful. Embedding initiated.",
            "time_taken_to_process": total_time,
        }

    except Exception as e:
        return {
            "admin_id": admin_id,
            "file_name": file_name,
            "status": "Extraction failed",
            "message": f"Error during extraction: {e}",
            "time_taken_to_process": int(time.time() - start),
        }



async def process_owner_files_async(owner: str, admin_id: str, db: AsyncSession) -> None:
    """
    Full async processing pipeline for all files in UPLOAD_ROOT/<owner>/... .
    Runs extractors, then embeddings, and updates UploadRecord + Document rows.
    """
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)

    owner_dir = UPLOAD_ROOT / owner
    if not owner_dir.exists():
        raise FileNotFoundError(f"Owner directory not found: {owner_dir}")

    await make_processing(db, admin_id)

    # Extract tasks
    extract_tasks: List = []
    for category_folder in owner_dir.iterdir():
        if not category_folder.is_dir():
            continue
        category = category_folder.name
        for fp in category_folder.glob("*"):
            if fp.is_file():
                extract_tasks.append(process_file(fp, category, admin_id))

    extract_results: List[Dict] = []
    if extract_tasks:
        extract_results = await asyncio.gather(*extract_tasks, return_exceptions=False)

    
    if extract_results:
        await update_db_statuses(db, extract_results)

   
    images_dir = IMAGE_OUTPUT_DIR 
    
   
    sanitized_owner = _clean_name(owner)

    image_upsert = upsert_image_folder(images_dir, sanitized_owner)
    embed_tasks: List = []
    output_dir = Path("output")
    if output_dir.exists():
        for fp in output_dir.iterdir():
            if fp.is_file():
                
                embed_tasks.append(upsert_documents_to_pinecone(str(fp), admin_id, owner))
    
    
    embed_tasks.append(image_upsert)

    embed_results_raw: List[Dict] = []
    if embed_tasks:
        embed_results_raw = await asyncio.gather(*embed_tasks, return_exceptions=False)

   
    embed_results: List[Dict] = []
    for r in embed_results_raw:
        if isinstance(r, dict):
            r.setdefault("admin_id", admin_id)
            embed_results.append(r)

    
    final_updates: List[Dict] = []
    for r in embed_results:
        raw_status = str(r.get("status", "")).lower()
        ok = raw_status == "processed"
        final_updates.append({
            "admin_id": admin_id,
            "file_name": r.get("file_name"),
            "status": "Processed" if ok else "Embedding failed",
            "message": r.get("message") if r.get("message") else ("File processed successfully." if ok else "Embedding failed."),
          
            "time_taken_to_process": r.get("time_taken_to_process", 0),
        })

    if final_updates:
        await update_db_statuses(db, final_updates)

    # Remove processed files directory
    await remove_old_folder(owner_dir)



def process_initiate_response(owner: str, admin_id: str) -> Dict:
    return {
        "message": "File processing initiated.",
        "owner": owner,
        "admin_id": admin_id,
        "status": "processing",
    }



async def get_admin_file_statuses(admin_id: str, db: AsyncSession) -> Dict:
    """
    Return a structured list of all UploadRecord rows for this admin.
    Matches the format you requested.
    """
    from sqlalchemy import select
    from app.models.models import UploadRecord

    result = await db.execute(
        select(
            UploadRecord.id,
            UploadRecord.file_name,
            UploadRecord.file_type,
            UploadRecord.status,
            UploadRecord.message,
            UploadRecord.upload_time,
            UploadRecord.processed_time,
            UploadRecord.time_taken_to_process,
            UploadRecord.is_deleted,
        ).where(
            UploadRecord.admin_id == admin_id,
            UploadRecord.is_deleted == False,
        )
    )
    rows = result.all()

    files: List[Dict] = []
    for row in rows:
        files.append({
            "file_id": row.id,
            "admin_id": admin_id,
            "file_name": row.file_name,
            "file_type": row.file_type,
            "category": row.file_type,  
            "status": row.status,
            "message": row.message,
            "upload_time": row.upload_time,
            "processed_time": row.processed_time,
            "time_taken_to_process": row.time_taken_to_process,
            "is_deleted": row.is_deleted,
        })

    return {
        "admin_id": admin_id,
        "files": files,
        "message": "No files found." if not files else f"{len(files)} file(s) found.",
    }



def _estimate_chunks(file_size: Optional[int]) -> Optional[int]:
    """Simple helper to estimate number of chunks from file size."""
    if not file_size:
        return None
    try:
        return max(1, int(file_size / 85_000))
    except Exception:
        return None
