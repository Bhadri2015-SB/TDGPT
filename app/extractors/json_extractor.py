import json
from pathlib import Path
from typing import Union, Any, Dict

import aiofiles

from app.utils.file_handler import change_to_processed


async def flatten_json_file(file_path: str) -> Dict[str, Any]:

    file = Path(file_path)
    output_path = Path("output") / f"{file.name}.json"

    try:
        async with aiofiles.open(file, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "json",
            "status": "error",
            "message": f"Failed to read JSON file: {e}"
        }

    

    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "json",
            "status": "error",
            "message": f"Failed to write flattened JSON: {e}"
        }

    await change_to_processed(str(file), "JSON")
    return data
