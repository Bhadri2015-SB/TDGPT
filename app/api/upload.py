from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
from app.utils.file_handler import save_file

from app.services.github_file_extraction import get_repo_files
from app.schemas.response_model import RepoInput


router = APIRouter()

@router.post("/upload/")
async def upload_files(owner_name: str = Form(...), files: List[UploadFile] = File(...)):
    saved_paths = []
    for file in files:
        path = await save_file(owner_name, file)
        saved_paths.append(path)
    return {
        "status": "success",
        "owner": owner_name,
        "saved_files": saved_paths
    }

@router.post("/extract-from-github/")
async def extract_files_from_github(data: RepoInput):
    try:
        result = await get_repo_files(data.repo_url)
        return {
            "message": "Files extracted and saved successfully.",
            "details": result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
