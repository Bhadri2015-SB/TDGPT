import json
from pathlib import Path
from typing import Any, Dict

import aiofiles
from markdown_it import MarkdownIt

from app.utils.file_handler import change_to_processed


async def extract_markdown_content(file_path: str, *_) -> Dict[str, Any]:
    """
    Extracts content from a Markdown file and writes structured data to a JSON output.

    Args:
        file_path (str): Path to the Markdown file.

    Returns:
        dict: Parsed markdown data and metadata.
    """
    file = Path(file_path)

    try:
        async with aiofiles.open(file, "r", encoding="utf-8") as f:
            text = await f.read()
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "markdown",
            "status": "error",
            "message": f"Failed to read Markdown file: {e}"
        }

    md = MarkdownIt()
    tokens = md.parse(text)

    content = []
    current_block = {}
    current_type = None

    for token in tokens:
        if token.type == "heading_open":
            current_type = "heading"
        elif token.type == "paragraph_open":
            current_type = "paragraph"
        elif token.type == "bullet_list_open":
            current_type = "list"
            current_block = {"type": "list", "items": []}
        elif token.type == "list_item_open":
            current_type = "list_item"
        elif token.type == "inline":
            content_text = token.content.strip()
            if current_type == "heading":
                content.append({"type": "heading", "text": content_text})
            elif current_type == "paragraph":
                content.append({"type": "paragraph", "text": content_text})
            elif current_type == "list_item":
                current_block["items"].append(content_text)
        elif token.type == "bullet_list_close":
            content.append(current_block)
            current_block = {}
        elif token.type == "fence":
            content.append({
                "type": "code_block",
                "language": token.info.strip(),
                "code": token.content
            })

    result = {
        "metadata": {
            "file_name": file.name,
            "file_type": "markdown",
            "file_size": f"{file.stat().st_size / 1024:.2f} KB"
        },
        "content": content,
        "summary": "Markdown parsed successfully",
        "total_time_taken": "0"  # Placeholder
    }

    output_path = Path("output") / f"{file.name}.json"
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "markdown",
            "status": "error",
            "message": f"Failed to write JSON output file: {e}"
        }

    await change_to_processed(str(file), "MD")
    return result
