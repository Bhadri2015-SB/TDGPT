from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services.database_service import create_upload_record, get_file_list, is_existing_file
from app.utils.file_handler import get_file_size, save_file
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.post("/upload/")
async def upload_files(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    saved_paths = []
    db_records = []
    try:
        for file in files:
            if await is_existing_file(db, user.id, file.filename):
                # raise HTTPException(
                #     status_code=400,
                #     detail=f"File '{file.filename}' already exists for user '{user.username}'."
                # )
                db_records.append({
                "file_name": file.filename,
                # "file_size": file_size,
                "upload_status": "file already exists"
                })
                continue
            path = await save_file(user.username, file)
            file_size = await get_file_size(file)
            record = await create_upload_record(
                user_id=user.id,
                file_name=file.filename,
                file_size=file_size,
                path=path,
                db=db
            )
            saved_paths.append(path)
            db_records.append({
                "file_name": file.filename,
                "file_size": file_size,
                "upload_status": record
            })
        return {
            "owner": user.username,
            "saved_files": saved_paths,
            "records": db_records
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files-status/")
async def list_files(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        return await get_file_list(user.id, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))