import json
import os
from pathlib import Path
from typing import Union, Any, Dict, List

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
    file = Path(file_path)
    try:
        async with aiofiles.open(file, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
    except Exception as e:
        return {"error": f"Failed to read JSON file: {e}"}

    flat = await flatten_json(data)

    # Build Word-like page structure containing flattened key-value pairs as a table
    headers = ["key", "value"]
    rows: List[List[str]] = [headers]
    for k, v in flat.items():
        try:
            val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        except Exception:
            val = str(v)
        rows.append([str(k), val])

    def table_html(rws: List[List[str]]) -> str:
        if not rws:
            return "<table></table>"
        html = ["<table>"]
        if len(rws) > 1:
            html.append("<thead>\n<tr>")
            html.extend([f"<th>{c}</th>" for c in rws[0]])
            html.append("</tr>\n</thead>")
            html.append("<tbody>")
            for rr in rws[1:]:
                html.append("<tr>")
                html.extend([f"<td>{c}</td>" for c in rr])
                html.append("</tr>")
            html.append("</tbody>")
        else:
            html.append("<tr>")
            html.extend([f"<td>{c}</td>" for c in rws[0]])
            html.append("</tr>")
        html.append("</table>")
        return "\n".join(html)

    def table_md(rws: List[List[str]]) -> str:
        if not rws:
            return ""
        if len(rws) == 1:
            return "| " + " | ".join(rws[0]) + " |"
        md = "| " + " | ".join(rws[0]) + " |\n"
        md += "| " + " | ".join(["-" * max(1, len(c)) for c in rws[0]]) + " |\n"
        for rr in rws[1:]:
            md += "| " + " | ".join(rr) + " |\n"
        return md.strip()

    def table_text(rws: List[List[str]]) -> str:
        if not rws:
            return ""
        widths = [0] * max(len(r) for r in rws)
        for r in rws:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(str(c)))
        lines = []
        for r in rws:
            cells = []
            for i in range(len(widths)):
                val = "" if i >= len(r) or r[i] is None else str(r[i])
                cells.append(val.ljust(widths[i]))
            lines.append("  ".join(cells).rstrip())
        return "\n".join(lines)

    table_item = {
        "type": "table",
        "rows": rows,
        "html": table_html(rows),
        "md": table_md(rows),
        "isPerfectTable": True,
        "csv": "",
        "bBox": {"x": 72.8, "y": 72.0, "w": 449.8, "h": 20 + (len(rows) * 25)},
    }

    page_number = 1
    text_block = table_text(rows)
    md_block = table_md(rows)

    page = {
        "page": page_number,
        "text": f"{text_block}\n\n{page_number}",
        "md": f"{md_block}\n\n{page_number}\n",
        "images": [{
            "name": f"page_{page_number}.jpg",
            "height": 841.889763779528,
            "width": 595.303937007874,
            "x": 0,
            "y": 0,
            "original_width": 2263,
            "original_height": 3200,
            "type": "full_page_screenshot",
        }],
        "charts": [],
        "items": [
            {"type": "heading", "value": f"JSON: {file.name}", "md": f"## JSON: {file.name}", "bBox": {"x": 72.8, "y": 40.0, "w": 449.8, "h": 28}, "lvl": 2},
            table_item,
        ],
        "status": "OK",
        "originalOrientationAngle": 0,
        "links": [],
        "width": 595.303937007874,
        "height": 841.889763779528,
        "triggeredAutoMode": False,
        "parsingMode": "premium",
        "structuredData": None,
        "noStructuredContent": False,
        "noTextContent": len(text_block.strip()) == 0,
        "pageHeaderMarkdown": f"JSON: {file.name}",
        "pageFooterMarkdown": f"\n{page_number}\n",
        "confidence": 1,
    }

    result = {"pages": [page]}

    base = os.path.splitext(file.name)[0]
    output_path = Path("output") / f"{base}.json.json"
    os.makedirs("output", exist_ok=True)
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return {"error": f"Failed to write flattened JSON: {e}"}

    await change_to_processed(str(file), "JSON")
    return result
