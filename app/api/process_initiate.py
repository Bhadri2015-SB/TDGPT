from fastapi import APIRouter, HTTPException, Form
from app.services.process_owner_files_async import process_owner_files_async


router = APIRouter()

@router.post("/process-owner-files/")
async def trigger_file_processing(owner: str = Form(...)):
    try:
        results = await process_owner_files_async(owner)
        return {"owner": owner, "processed_files": results}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Processing error: " + str(e))


    

