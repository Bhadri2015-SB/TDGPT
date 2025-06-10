import json
import os
import aiofiles
from markdown_it import MarkdownIt

from app.utils.file_handler import change_to_processed

async def extract_markdown_content(file_path, *_):
    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
        text = await f.read()

    md = MarkdownIt()
    tokens = md.parse(text)
    content, block, block_type = [], {}, None

    for token in tokens:
        if token.type == "heading_open": block_type = "heading"
        elif token.type == "paragraph_open": block_type = "paragraph"
        elif token.type == "bullet_list_open": block_type, block = "list", {"type": "list", "items": []}
        elif token.type == "list_item_open": block_type = "list_item"
        elif token.type == "inline":
            c = token.content.strip()
            if block_type == "heading": content.append({"type": "heading", "text": c})
            elif block_type == "paragraph": content.append({"type": "paragraph", "text": c})
            elif block_type == "list_item": block["items"].append(c)
        elif token.type == "bullet_list_close":
            content.append(block); block = {}
        elif token.type == "fence":
            content.append({"type": "code_block", "language": token.info.strip(), "code": token.content})
    

    file_name = os.path.basename(file_path)
    result = {
        "metadata": {
            "file_name": file_name,
            "file_type": "markdown",
            "file_size": f"{os.path.getsize(file_path)/1024:.2f} KB"
        },
        "content": content,
        "summary": "Markdown parsed successfully"
    }

    print("end of markdown extractor")

    try:
        async with aiofiles.open(f"output/{file_name}.json", "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "Markdown")

    return result

