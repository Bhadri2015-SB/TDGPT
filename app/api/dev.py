from fastapi import APIRouter, HTTPException, Form
from app.services.process_owner_files_async import process_file


router = APIRouter()

@router.post("/process-single-files/")
async def trigger_file_processing(path: str = Form(...)):
    try:
        results = await process_file(path, "Word")
        return {"process": "success", "processed_files": results}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Processing error: " + str(e))


    

