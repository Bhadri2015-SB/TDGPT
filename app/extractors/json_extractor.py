import json
from pathlib import Path
from typing import Union

import aiofiles

from app.utils.file_handler import change_to_processed


async def flatten_json(data: Union[dict, list], prefix: str = '') -> dict:
    
    out = {}

    def recurse(obj, path=""):
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


async def flatten_json_file(file_path: str) -> dict:
    file_name = Path(file_path).name
    output_path: str = f"output/{file_name}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = await flatten_json(data)

    print("end of json extractor")

    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "JSON")

    return result
