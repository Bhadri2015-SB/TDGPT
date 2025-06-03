from fastapi import APIRouter, UploadFile, File, Form
from typing import List
from app.utils.file_handler import save_file

router = APIRouter()

@router.post("/upload/")
async def upload_files(owner_name: str = Form(...), files: List[UploadFile] = File(...)):
    saved_paths = []
    for file in files:
        path = save_file(owner_name, file)
        saved_paths.append(path)
    return {
        "status": "success",
        "owner": owner_name,
        "saved_files": saved_paths
    }
