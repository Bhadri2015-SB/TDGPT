from fastapi import APIRouter, HTTPException
from app.services import process_owner_files_async


router = APIRouter()

@router.post("/process-owner-files/{owner}")
async def trigger_file_processing(owner: str):
    try:
        results = await process_owner_files_async(owner)
        return {"owner": owner, "processed_files": results}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Processing error: " + str(e))


    

