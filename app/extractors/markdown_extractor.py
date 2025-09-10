import json
import re
from pathlib import Path
from typing import Any, Dict, List

import aiofiles
from markdown_it import MarkdownIt

from app.utils.file_handler import change_to_processed


def create_markdown_from_text(text: str) -> str:
    if not text or not text.strip():
        return ""
    md = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            md.append("")
        elif re.match(r"^\d+\.\d+(?:\.\d+)*\s+\S+", s):
            md.append(f"### {s}")
        elif re.match(r"^\d+\.?\s+\S+", s):
            md.append(f"## {s}")
        elif len(s) < 50 and s.isupper() and len(s) > 3:
            md.append(f"# {s}")
        else:
            md.append(s)
    return "\n".join(md)


def _items_from_md_tokens(tokens) -> List[dict]:
    items: List[dict] = []
    y = 72.0
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open":
            # next inline contains text
            j = i + 1
            text_val = ""
            while j < len(tokens) and tokens[j].type != "heading_close":
                if tokens[j].type == "inline":
                    text_val = tokens[j].content.strip()
                j += 1
            height = 26
            width = min(449.8, max(7, len(text_val)) * 7)
            lvl = 1
            # determine level from tag (h1..h6)
            try:
                tag = t.tag.lower()
                if tag.startswith("h") and tag[1:].isdigit():
                    lvl_num = int(tag[1:])
                    if lvl_num == 1:
                        lvl = 1
                    elif lvl_num == 2:
                        lvl = 2
                    else:
                        lvl = 3
            except Exception:
                pass
            items.append({
                "type": "heading",
                "value": text_val,
                "md": create_markdown_from_text(text_val),
                "bBox": {"x": 72.8, "y": y, "w": width, "h": height},
                "lvl": lvl,
            })
            y += height + 10
            i = j
        elif t.type == "paragraph_open":
            j = i + 1
            text_val = ""
            while j < len(tokens) and tokens[j].type != "paragraph_close":
                if tokens[j].type == "inline":
                    text_val += tokens[j].content
                j += 1
            text_val = text_val.strip()
            lines = text_val.splitlines() or [text_val]
            height = 12 + (len(lines) * 14)
            width = min(449.8, max(7, len(text_val)) * 7)
            items.append({
                "type": "text",
                "value": text_val,
                "md": create_markdown_from_text(text_val),
                "bBox": {"x": 72.8, "y": y, "w": width, "h": height},
            })
            y += height + 10
            i = j
        elif t.type == "bullet_list_open":
            # aggregate list items
            j = i + 1
            list_items: List[str] = []
            while j < len(tokens) and tokens[j].type != "bullet_list_close":
                if tokens[j].type == "inline":
                    list_items.append(tokens[j].content.strip())
                j += 1
            text_val = "\n".join(f"- {s}" for s in list_items)
            lines = text_val.splitlines() or [text_val]
            height = 12 + (len(lines) * 14)
            width = min(449.8, max(7, len(text_val)) * 7)
            items.append({
                "type": "text",
                "value": text_val,
                "md": create_markdown_from_text(text_val),
                "bBox": {"x": 72.8, "y": y, "w": width, "h": height},
            })
            y += height + 10
            i = j
        elif t.type == "fence":
            code_lang = t.info.strip()
            code_text = t.content
            text_val = f"```{code_lang}\n{code_text}\n```" if code_lang else f"```\n{code_text}\n```"
            lines = text_val.splitlines() or [text_val]
            height = 12 + (len(lines) * 14)
            width = 449.8
            items.append({
                "type": "text",
                "value": text_val,
                "md": text_val,
                "bBox": {"x": 72.8, "y": y, "w": width, "h": height},
            })
            y += height + 10
        i += 1
    return items


async def extract_markdown_content(file_path: str, *_) -> Dict[str, Any]:
    file = Path(file_path)

    try:
        async with aiofiles.open(file, "r", encoding="utf-8") as f:
            text = await f.read()
    except Exception as e:
        return {"error": f"Failed to read Markdown file: {e}"}

    md = MarkdownIt()
    tokens = md.parse(text)

    # Simple single-page output matching Word schema.
    items = _items_from_md_tokens(tokens)

    md_content = create_markdown_from_text(text)
    if not md_content.strip().endswith("1"):
        md_content = f"{md_content}\n\n1\n"

    page = {
        "page": 1,
        "text": f"{text}\n\n1",
        "md": md_content,
        "images": [{
            "name": "page_1.jpg",
            "height": 841.889763779528,
            "width": 595.303937007874,
            "x": 0,
            "y": 0,
            "original_width": 2263,
            "original_height": 3200,
            "type": "full_page_screenshot",
        }],
        "charts": [],
        "items": items,
        "status": "OK",
        "originalOrientationAngle": 0,
        "links": [],
        "width": 595.303937007874,
        "height": 841.889763779528,
        "triggeredAutoMode": False,
        "parsingMode": "premium",
        "structuredData": None,
        "noStructuredContent": False,
        "noTextContent": len(text.strip()) == 0,
        "pageHeaderMarkdown": "",
        "pageFooterMarkdown": "\n1\n",
        "confidence": 1,
    }

    result = {"pages": [page]}

    output_path = Path("output") / f"{file.name}.json"
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        return {"error": f"Failed to write JSON output file: {e}"}

    await change_to_processed(str(file), "MD")
    return result
