import json
from pathlib import Path
from typing import Union, Any, Dict

import aiofiles
from app.core.logger import app_logger 

from app.utils.file_handler import change_to_processed


async def flatten_json(data: Union[dict, list], prefix: str = '') -> Dict[str, Any]:
    """
    Recursively flattens a nested JSON structure.
    """
    out = {}

    def recurse(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                recurse(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                recurse(v, f"{path}[{i}]")
        else:
            out[path] = obj

    recurse(data, prefix)
    return out


async def flatten_json_file(file_path: str) -> Dict[str, Any]:
    """
    Reads and flattens a JSON file, saving the output to a file.
    """
    file = Path(file_path)
    output_path = Path("output") / f"{file.name}.json"

    app_logger.info(f" Starting JSON flattening for: {file_path}")

    try:
        async with aiofiles.open(file, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
            app_logger.debug(f" Loaded JSON content from {file.name}")
    except Exception as e:
        app_logger.exception(f" Failed to read JSON file {file.name}: {e}")
        return {
            "file_name": file.name,
            "file_type": "json",
            "status": "error",
            "message": f"Failed to read JSON file: {e}"
        }

    try:
        result = await flatten_json(data)
        app_logger.info(f" Flattened JSON for: {file.name}")
    except Exception as e:
        app_logger.exception(f" Failed to flatten JSON for {file.name}: {e}")
        return {
            "file_name": file.name,
            "file_type": "json",
            "status": "error",
            "message": f"Failed to flatten JSON content: {e}"
        }

    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
            app_logger.info(f" Saved flattened JSON to: {output_path}")
    except Exception as e:
        app_logger.exception(f" Failed to write flattened JSON for {file.name}: {e}")
        return {
            "file_name": file.name,
            "file_type": "json",
            "status": "error",
            "message": f"Failed to write flattened JSON: {e}"
        }

    await change_to_processed(str(file), "JSON")
    app_logger.info(f" Moved {file.name} to processed folder.")

    return result
