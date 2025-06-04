import json
from typing import Union


def flatten_json(data: Union[dict, list], prefix: str = '') -> dict:
    """
    Recursively flattens nested JSON/dict/list into a flat dictionary.
    Keys are joined using dot notation and square brackets for list indices.

    Args:
        data (dict or list): Loaded JSON object
        prefix (str): Internal use only for recursive path building

    Returns:
        dict: Flattened key-path to value mapping
    """
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
    """
    Loads a JSON file, flattens it, and returns the result.
    Optionally saves the output to a new JSON file.

    Args:
        file_path (str): Path to the input JSON file
        save_output (bool): Whether to save the flattened JSON to a file
        output_path (str): Path to save output if save_output is True

    Returns:
        dict: Flattened JSON dictionary
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    flattened = flatten_json(data)

    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(flattened, f, indent=2)

    return flattened
