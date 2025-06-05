import json
from typing import Union


def flatten_json(data: Union[dict, list], prefix: str = '') -> dict:
    
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


def flatten_json_file(file_path: str, output_path: str = "output/json_output.json") -> dict:
    
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    flattened = flatten_json(data)

    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(flattened, f, indent=2)

    return flattened
