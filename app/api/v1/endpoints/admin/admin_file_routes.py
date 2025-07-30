from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import os

from app.db.session import get_db
from app.models.models import Admin
from app.core.security import get_current_admin
from app.utils.file_handler import save_file
from app.services.database_service import create_upload_record, get_file_list
from app.services.process_owner_files_async import (
    process_owner_files_async,
    process_initiate_response,
    get_admin_file_statuses,
)
from app.tasks.file_tasks import start_processing

router = APIRouter(tags=["admin"])


@router.post("/upload/")
async def upload_files(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin)
):
    admin_id = current_admin.id
    admin_name = current_admin.admin_name
    uploaded = []

    for file in files:
        file_path = await save_file(admin_name, file)
        file_size = os.path.getsize(file_path)
        result = await create_upload_record(
            admin_id=admin_id,
            file_name=file.filename,
            file_size=file_size,
            path=file_path,
            db=db
        )
        uploaded.append({"file": file.filename, "status": result})

    return {"uploaded_files": uploaded}



@router.get("/files-status/")
async def list_files(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin)
):
    files = await get_file_list(current_admin.id, db)
    return {"files": files}



@router.post("/process/initiate")
async def initiate_file_processing(
    owner: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin)
):
    background_tasks.add_task(process_owner_files_async, owner, current_admin.id, db)
    return process_initiate_response(owner, current_admin.id)



@router.get("/process/status")
async def get_file_processing_status(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin)
):
    return await get_admin_file_statuses(current_admin.id, db)



@router.post("/process/trigger-task")
async def trigger_file_processing(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin)
):
    background_tasks.add_task(start_processing, current_admin.admin_name, current_admin.id)
    return {"message": f"Processing initiated for {current_admin.admin_name}."}



@router.get("/process/file-process-status/")
async def get_task_file_processing_status(
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin)
):
    files = await get_file_list(current_admin.id, db)
    return {"files": files}
