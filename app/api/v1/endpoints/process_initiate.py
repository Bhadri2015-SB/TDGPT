import asyncio
from fastapi import APIRouter, Depends, HTTPException, Form
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import User
# from app.services.database_service import mark_batch_as_processed
# from app.services.process_owner_files_async import process_owner_files_async
from sqlalchemy.ext.asyncio import AsyncSession
from app.tasks.file_tasks import start_processing#process_owner_files_task

router = APIRouter()

@router.post("/initiate-file-process/")
async def trigger_file_processing(user:User = Depends(get_current_user)):
    
    try:
        # Clone the user info to pass (not the db session)
        username = user.username
        user_id = user.id

        # Schedule the background task (don't await it)
        asyncio.create_task(start_processing(username, user_id))

        return {"owner": username, "process_status": "Process initiated"}
        # process_owner_files_task.delay(user.username, user.id)
        # return {"owner": user.username, "process_status": "process initiated"}
    # try:
    #     results = await process_owner_files_async(user.username, user.id, db)
    #     return {"owner": user.username, "processed_files": results}
        # await mark_batch_as_processed(db, user.id)
        # return {"owner": user.username, "process_status": "process initiated"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Processing error: " + str(e))


    

    

