from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio

from app.schemas.response_model import RepoInput
from app.services import process_owner_files_async
from app.services.github_file_extraction import get_repo_files

router = FastAPI()

@router.post("/process-owner-files/{owner}")
async def trigger_file_processing(owner: str):
    try:
        results = await process_owner_files_async(owner)
        return {"owner": owner, "processed_files": results}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Processing error: " + str(e))

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
    

