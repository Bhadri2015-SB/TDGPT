import os
import aiofiles
from markdown_it import MarkdownIt

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

    return {
        "metadata": {
            "file_name": os.path.basename(file_path),
            "file_type": "markdown",
            "file_size": f"{os.path.getsize(file_path)/1024:.2f} KB"
        },
        "content": content,
        "summary": "Markdown parsed successfully"
    }

