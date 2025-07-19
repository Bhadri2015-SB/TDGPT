import os
import time
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import OUTPUT_DIRECTORY
from app.services.extractors import PROCESSOR_MAP
from app.utils.file_handler import delete_non_empty_dir, get_file_category, remove_old_folder
from app.utils.file_handler import UPLOAD_ROOT
from app.services.database_service import make_processing, update_db_statuses, create_document_record, update_document_processing_status
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
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    owner_dir = UPLOAD_ROOT / owner
    if not owner_dir.exists():
        raise FileNotFoundError("Owner directory not found")

    await make_processing(db, user_id)
    
    # Create Document records for all files being processed
    await create_document_records_for_files(owner, user_id, db)

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
    await delete_non_empty_dir('output/images')
    print("\n-------------------extraction end---------------------------\n")
    


    vector_store=[]
    folder_path = "output"
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        print(f"\n\nProcessing file: {file_path}\n\n")
        if os.path.isfile(file_path):
            #storing in vector db
            vector_store.append(upsert_documents_to_pinecone(file_path,user_id,owner))
    print("\n-------------------await start---------------------------\n")
    results = await asyncio.gather(*vector_store, return_exceptions=False)
    await update_db_statuses(db, results)
    
    # Update Document records with processing results
    await update_document_records_after_processing(results, db)
    
    # Clean up old folder
    print("\n-------------------stored end---------------------------\n")
    await delete_non_empty_dir('output')
    await remove_old_folder(owner_dir)

    return results


async def create_document_records_for_files(owner: str, user_id: str, db: AsyncSession):
    """
    Create Document records for all files being processed.
    
    Args:
        owner (str): Directory name corresponding to the owner.
        user_id (str): The user's ID.
        db (AsyncSession): Async database session.
    """
    from app.models.models import UploadRecord
    from sqlalchemy import select
    from datetime import datetime
    
    try:
        # Get all upload records for this user that are being processed
        result = await db.execute(
            select(UploadRecord).where(
                UploadRecord.user_id == user_id,
                UploadRecord.status.in_(["processing", "Processing"]),
                UploadRecord.is_deleted == False
            )
        )
        upload_records = result.scalars().all()
        
        owner_dir = UPLOAD_ROOT / owner
        
        for upload_record in upload_records:
            # Find the actual file path
            file_found = False
            for category_folder in owner_dir.iterdir():
                if not category_folder.is_dir():
                    continue
                    
                for file_path in category_folder.glob("*"):
                    if file_path.is_file() and file_path.name == upload_record.file_name:
                        # Create document record
                        document_id = await create_document_record(
                            user_id=user_id,
                            upload_record_id=upload_record.id,
                            file_path=str(file_path),
                            file_size=upload_record.file_size,
                            file_type=upload_record.file_type,
                            db=db,
                            processing_status="processing",
                            processing_started_at=datetime.utcnow(),
                            embedding_model="text-embedding-3-small",
                            pinecone_index_name="tdgpt",
                            total_chunks=0  # Will be updated after processing
                        )
                        
                        if document_id:
                            print(f"Created document record {document_id} for file {upload_record.file_name}")
                        else:
                            print(f"Failed to create document record for file {upload_record.file_name}")
                        
                        file_found = True
                        break
                
                if file_found:
                    break
                    
    except Exception as e:
        print(f"Error creating document records: {e}")


async def update_document_records_after_processing(results: list, db: AsyncSession):
    """
    Update Document records with processing results.
    
    Args:
        results (list): List of processing results.
        db (AsyncSession): Async database session.
    """
    from app.models.models import UploadRecord, Document
    from sqlalchemy import select
    from datetime import datetime
    
    for result in results:
        if not isinstance(result, dict):
            continue
            
        file_name = result.get("file_name")
        status = result.get("status")
        user_id = result.get("user_id")
        
        if not all([file_name, status, user_id]):
            continue
            
        try:
            # Get upload record
            upload_result = await db.execute(
                select(UploadRecord).where(
                    UploadRecord.user_id == user_id,
                    UploadRecord.file_name == file_name,
                    UploadRecord.is_deleted == False
                )
            )
            upload_record = upload_result.scalar_one_or_none()
            
            if not upload_record:
                continue
                
            # Get document record
            doc_result = await db.execute(
                select(Document).where(
                    Document.upload_record_id == upload_record.id,
                    Document.is_deleted == False
                )
            )
            document = doc_result.scalar_one_or_none()
            
            if not document:
                continue
                
            # Update document status based on processing result
            if status in ["Processed", "Processing"]:
                processing_status = "completed" if status == "Processed" else "processing"
                processing_completed_at = datetime.utcnow() if status == "Processed" else None
                
                # Set embedding details if successful
                embedding_model = "BAAI/bge-small-en-v1.5" if status == "Processed" else None
                pinecone_index_name = "llamaintegration" if status == "Processed" else None  # cleaned name
                
                # Estimate chunk count based on file size (rough approximation)
                # Based on observed data: ~50,000-120,000 bytes per chunk for PDF files
                # Using average of 85,000 bytes per chunk
                estimated_chunks = None
                if status == "Processed" and document.file_size:
                    estimated_chunks = max(1, int(document.file_size / 85000))
                
                await update_document_processing_status(
                    db=db,
                    document_id=document.id,
                    processing_status=processing_status,
                    processing_completed_at=processing_completed_at,
                    embedding_model=embedding_model,
                    pinecone_index_name=pinecone_index_name,
                    total_chunks=estimated_chunks
                )
                
                print(f"Updated document {document.id} status to {processing_status}")
                
            elif "failed" in status.lower() or "error" in status.lower():
                await update_document_processing_status(
                    db=db,
                    document_id=document.id,
                    processing_status="failed",
                    processing_error=result.get("message", "Unknown error"),
                    processing_completed_at=datetime.utcnow()
                )
                
                print(f"Updated document {document.id} status to failed")
                
        except Exception as e:
            print(f"Error updating document record for {file_name}: {e}")





















