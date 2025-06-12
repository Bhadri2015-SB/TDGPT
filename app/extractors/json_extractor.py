import json
from pathlib import Path
from typing import Union, Any, Dict

import aiofiles

from app.utils.file_handler import change_to_processed


async def flatten_json(data: Union[dict, list], prefix: str = '') -> Dict[str, Any]:
    """
    Recursively flattens a nested JSON structure.

    Args:
        data (Union[dict, list]): The JSON data to flatten.
        prefix (str): Optional prefix for keys (used in recursion).

    Returns:
        dict: Flattened JSON.
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

    Args:
        file_path (str): Path to the input JSON file.

    Returns:
        dict: Flattened JSON content.
    """
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

    result = await flatten_json(data)

    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "json",
            "status": "error",
            "message": f"Failed to write flattened JSON: {e}"
        }

    await change_to_processed(str(file), "JSON")
    return result
