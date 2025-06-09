from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from typing import List
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import User
from app.services.database_service import create_upload_batch
from app.utils.file_handler import get_file_size, save_file

from app.services.github_file_extraction import get_repo_files
from app.schemas.response_model import RepoInput
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter()

@router.post("/upload/")
async def upload_files(files: List[UploadFile] = File(...), user:User=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    saved_paths = []
    file_sizes = 0
    file_names = []
    for file in files:
        path = await save_file(user.username, file)
        file_sizes += await get_file_size(file)
        file_names.append(file.filename)
        saved_paths.append(path)

    status=await create_upload_batch(
        user_id=user.id,
        file_names=file_names,
        total_size=file_sizes,
        db=db)

    return {
        "db_status": status,
        "owner": user.username,
        "saved_files": saved_paths
    }

@router.post("/extract-from-github/")
async def extract_files_from_github(data: RepoInput, user:User=Depends(get_current_user)):
    try:
        result = await get_repo_files(data.repo_url)
        return {
            "message": "Files extracted and saved successfully.",
            "details": result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
