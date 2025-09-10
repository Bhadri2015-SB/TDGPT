import os
import io
import time
import json
import re
import fitz
import aiofiles
import pdfplumber
from PIL import Image as PILImage
import pytesseract
from typing import List
from app.utils.file_handler import change_to_processed


async def ensure_dirs():
    """Ensure required directories match Word extractor (output/images + summary/vision)."""
    img_root = os.path.join("output", "images")
    img_summary_dir = os.path.join(img_root, "summary")
    img_vision_dir = os.path.join(img_root, "vision")
    os.makedirs(img_root, exist_ok=True)
    os.makedirs(img_summary_dir, exist_ok=True)
    os.makedirs(img_vision_dir, exist_ok=True)
    return img_root, img_summary_dir, img_vision_dir


def create_markdown_from_text(text: str) -> str:
    if not text or not text.strip():
        return ""
    lines = text.split('\n')
    md = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            md.append("")
        elif re.match(r'^\d+\.\d+(?:\.\d+)*\s+\S+', line):
            md.append(f"### {line}")
        elif re.match(r'^\d+\.?\s+\S+', line):
            md.append(f"## {line}")
        elif len(line) < 50 and line.isupper() and len(line) > 3:
            md.append(f"# {line}")
        else:
            md.append(line)
        i += 1
    return "\n".join(md)


def create_table_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    if len(rows) == 1:
        return "| " + " | ".join(rows[0]) + " |"
    md = "| " + " | ".join(rows[0]) + " |\n"
    md += "| " + " | ".join(["-" * len(cell) for cell in rows[0]]) + " |\n"
    for row in rows[1:]:
        md += "| " + " | ".join(row) + " |\n"
    return md.strip()


def create_html_table_from_data(table_data: List[List[str]]) -> str:
    if not table_data:
        return ""
    html = "\n<table>\n<thead>\n<tr>\n"
    for cell in table_data[0]:
        html += f"<th>{cell}</th>\n"
    html += "</tr>\n</thead>\n<tbody>\n"
    for row in table_data[1:]:
        html += "<tr>\n"
        for cell in row:
            html += f"<td>{cell}</td>\n"
        html += "</tr>\n"
    html += "</tbody>\n</table>\n\n"
    return html


def create_table_csv(rows: List[List[str]]) -> str:
    import io as _io, csv as _csv
    buf = _io.StringIO()
    w = _csv.writer(buf, quoting=_csv.QUOTE_ALL, lineterminator='\n')
    for r in rows:
        w.writerow(["" if c is None else str(c) for c in r])
    return buf.getvalue().replace('\r\n', '\n').rstrip("\n")


def create_table_plain_text(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    num_cols = max(len(r) for r in rows)
    col_widths = [0] * num_cols
    for r in rows:
        for i, c in enumerate(r):
            col_widths[i] = max(col_widths[i], len(str(c)))
    lines = []
    for r in rows:
        cells = []
        for i in range(num_cols):
            val = "" if i >= len(r) or r[i] is None else str(r[i])
            cells.append(val.ljust(col_widths[i]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def create_item_from_text(text: str, y_position: float) -> dict:
    text = text.strip()
    item_type = "text"
    level = None
    if re.match(r'^\d+\.\d+(?:\.\d+)*\s+\S+', text):
        item_type = "heading"; level = 3
    elif re.match(r'^\d+\.?\s+\S+', text):
        item_type = "heading"; level = 2
    elif text.isupper() and 3 < len(text) < 50:
        item_type = "heading"; level = 1
    if '|' in text and text.count('|') >= 2:
        rows = []
        for line in text.split('\n'):
            if '|' in line:
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                if cells:
                    rows.append(cells)
        return {
            "type": "table",
            "rows": rows,
            "html": create_html_table_from_data(rows),
            "md": create_table_markdown(rows),
            "isPerfectTable": True,
            "csv": create_table_csv(rows),
            "bBox": {"x": 72.8, "y": y_position, "w": 449.8, "h": 20 + (len(rows) * 25)}
        }
    height = 12 + (len(text.split('\n')) * 14)
    width = min(449.8, max(7, len(text)) * 7)
    item = {
        "type": item_type,
        "value": text,
        "md": create_markdown_from_text(text),
        "bBox": {"x": 72.8, "y": y_position, "w": width, "h": height}
    }
    if level:
        item["lvl"] = level
    return item


def create_comprehensive_items(text: str) -> List[dict]:
    if not text or not text.strip():
        return []
    items = []
    lines = text.split('\n')
    y = 72.0
    para = []
    for line in lines:
        line = line.strip()
        if not line:
            if para:
                t = '\n'.join(para)
                it = create_item_from_text(t, y)
                items.append(it)
                y += it["bBox"]["h"] + 10
                para = []
            continue
        if (line.isupper() and len(line) < 50) or re.match(r'^\d+\.?\s+[A-Z]', line) or line.startswith(('Table', 'Figure', 'Chart')):
            if para:
                t = '\n'.join(para)
                it = create_item_from_text(t, y)
                items.append(it)
                y += it["bBox"]["h"] + 10
                para = []
            it = create_item_from_text(line, y)
            items.append(it)
            y += it["bBox"]["h"] + 10
        else:
            para.append(line)
    if para:
        t = '\n'.join(para)
        it = create_item_from_text(t, y)
        items.append(it)
    return items


def create_comprehensive_items_with_tables(text: str, tables: List[List[List[str]]]) -> List[dict]:
    text_items = create_comprehensive_items(text)
    if text_items:
        last = text_items[-1]
        y = last["bBox"]["y"] + last["bBox"]["h"] + 20
    else:
        y = 72.0
    items = list(text_items)
    for table in tables:
        if table and len(table) > 0:
            table_item = {
                "type": "table",
                "rows": table,
                "html": create_html_table_from_data(table),
                "md": create_table_markdown(table),
                "isPerfectTable": True,
                "csv": create_table_csv(table),
                "bBox": {"x": 72.8, "y": y, "w": 449.8, "h": 20 + (len(table) * 25)}
            }
            items.append(table_item)
            y += table_item["bBox"]["h"] + 20
    return items


def create_comprehensive_pages_structure(pages_data: List[dict], filename: str) -> List[dict]:
    pages = []
    for page_data in pages_data:
        page_text = page_data.get("text", "")
        page_images = page_data.get("images", [])
        page_number = page_data.get("page_num", len(pages) + 1)
        page_tables = page_data.get("tables", [])
        pos_items = page_data.get("items_positional") or []
        if pos_items:
            items = list(pos_items) + create_comprehensive_items_with_tables("", page_tables)
        else:
            items = create_comprehensive_items_with_tables(page_text, page_tables)
        md_content = create_markdown_from_text(page_text)
        for table_data in page_tables:
            table_md = create_table_markdown(table_data)
            md_content += f"\n\n{table_md}\n"
        text_with_tables = page_text
        for table_data in page_tables:
            pt = create_table_plain_text(table_data)
            if pt:
                text_with_tables = f"{text_with_tables}\n\n{pt}"
        last_line = (text_with_tables.strip().splitlines() or [""])[-1]
        if last_line.strip() != str(page_number):
            text_with_tables = f"{text_with_tables}\n\n{page_number}"
        page_images_with_screenshot = list(page_images) + [{
            "name": f"page_{page_number}.jpg",
            "height": 841.889763779528,
            "width": 595.303937007874,
            "x": 0,
            "y": 0,
            "original_width": 2263,
            "original_height": 3200,
            "type": "full_page_screenshot"
        }]
        page_header = ""
        page_footer = f"\n{page_number}\n"
        page_structure = {
            "page": page_number,
            "text": text_with_tables,
            "md": f"{md_content}\n\n{page_number}\n",
            "images": page_images_with_screenshot,
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
            "noTextContent": len(text_with_tables.strip()) == 0,
            "pageHeaderMarkdown": page_header,
            "pageFooterMarkdown": page_footer,
            "confidence": 1,
        }
        pages.append(page_structure)
    return pages


async def extract_pdf_content(file_path):
    start_time = time.time()
    filename = os.path.splitext(os.path.basename(file_path))[0]

    
    try:
        if os.name == 'nt':
            for p in [
                r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
                r"C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
            ]:
                if os.path.exists(p):
                    pytesseract.pytesseract.tesseract_cmd = p
                    break
    except Exception:
        pass

    img_root, img_summary_dir, img_vision_dir = await ensure_dirs()

    try:
        pdf = fitz.open(file_path)
        plumber_pdf = pdfplumber.open(file_path)
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF: {e}")

    pages_collected: List[dict] = []

    for i, (fz_page, pl_page) in enumerate(zip(pdf, plumber_pdf.pages), start=1):
        page_text = (fz_page.get_text("text") or "").strip()

        
        tables_rows: List[List[List[str]]] = []
        try:
            tables_raw = pl_page.extract_tables() or []
            for t in tables_raw:
                if t and any(any(cell for cell in row) for row in t):
                    tables_rows.append([["" if cell is None else str(cell).strip() for cell in row] for row in t])
        except Exception:
            pass

        
        page_text_items: List[dict] = []
        image_blocks: List[dict] = []
        try:
            raw = fz_page.get_text("rawdict") or {}
            blocks = raw.get("blocks", [])
            for blk in blocks:
                btype = blk.get("type")
                if btype == 0 and "bbox" in blk and blk.get("lines"):
                    lines = blk.get("lines", [])
                    texts = []
                    for ln in lines:
                        spans = ln.get("spans", [])
                        span_txt = "".join(sp.get("text", "") for sp in spans)
                        if span_txt.strip():
                            texts.append(span_txt)
                    text_val = "\n".join(texts).strip()
                    if text_val:
                        x0, y0, x1, y1 = blk["bbox"]
                        w = float(x1 - x0)
                        h = float(y1 - y0)
                        lvl = None
                        item_type = "text"
                        first_line = (texts[0] if texts else text_val).strip()
                        if re.match(r'^\d+\.\d+(?:\.\d+)*\s+\S+', first_line):
                            item_type = "heading"; lvl = 3
                        elif re.match(r'^\d+\.?\s+\S+', first_line):
                            item_type = "heading"; lvl = 2
                        elif len(first_line) < 50 and first_line.isupper() and len(first_line) > 3:
                            item_type = "heading"; lvl = 1
                        page_text_items.append({
                            "type": item_type,
                            "value": text_val,
                            "md": create_markdown_from_text(text_val),
                            "bBox": {"x": float(x0), "y": float(y0), "w": w, "h": h},
                            **({"lvl": lvl} if lvl else {})
                        })
                elif btype == 1 and "bbox" in blk:
                    image_blocks.append({"bbox": blk["bbox"]})
        except Exception:
            pass

        # Extract inline images with coordinates and OCR
        page_images: List[dict] = []
        try:
            image_blocks_sorted = sorted(image_blocks, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
            for img_idx, blk in enumerate(image_blocks_sorted, start=1):
                bbox = blk["bbox"]
                rect = fitz.Rect(bbox)
                try:
                    pix_clip = fz_page.get_pixmap(dpi=150, clip=rect)
                    img_name = f"img_p{i}_{img_idx}.png"
                    img_path = os.path.join(img_root, img_name)
                    pix_clip.save(img_path)

                    # OCR words
                    ocr_items = []
                    try:
                        pil_img = PILImage.open(img_path).convert("RGB")
                        data = pytesseract.image_to_data(
                            pil_img,
                            lang="eng",
                            config="--oem 3 --psm 6",
                            output_type=pytesseract.Output.DICT,
                        )
                        n = len(data.get("text", []))
                        for j in range(n):
                            txt = (data["text"][j] or "").strip()
                            if not txt:
                                continue
                            conf_raw = data.get("conf", ["-1"])[j]
                            try:
                                conf = float(conf_raw)
                            except Exception:
                                conf = -1.0
                            ocr_items.append({
                                "x": int(data.get("left", [0])[j]),
                                "y": int(data.get("top", [0])[j]),
                                "w": int(data.get("width", [0])[j]),
                                "h": int(data.get("height", [0])[j]),
                                "confidence": conf,
                                "text": txt,
                            })
                    except Exception:
                        pass

                    page_images.append({
                        "name": img_name,
                        "height": pix_clip.height,
                        "width": pix_clip.width,
                        "x": float(rect.x0),
                        "y": float(rect.y0),
                        "original_width": pix_clip.width,
                        "original_height": pix_clip.height,
                        "ocr": ocr_items,
                        "type": "inline_image",
                    })
                except Exception:
                    continue
        except Exception:
            pass

        try:
            def cy(b):
                return float(b.get("y", 0)) + float(b.get("h", 0)) / 2.0
            text_items_sorted = sorted(
                [ti for ti in page_text_items if ti.get("type") in ("text", "heading") and ti.get("bBox")],
                key=lambda t: cy(t["bBox"]) )
            for img in page_images:
                ib = {"x": img.get("x", 0), "y": img.get("y", 0), "w": img.get("width", 0), "h": img.get("height", 0)}
                icy = cy(ib)
                above = None; below = None; head = None
                for ti in text_items_sorted:
                    tcy = cy(ti["bBox"]) 
                    if tcy <= icy:
                        above = ti
                    elif tcy > icy and below is None:
                        below = ti
                headings = [ti for ti in text_items_sorted if ti.get("type") == "heading"]
                if headings:
                    head = min(headings, key=lambda h: abs(cy(h["bBox"]) - icy))
                img["anchors"] = {
                    "above_text": {"text": above.get("value") if above else None},
                    "below_text": {"text": below.get("value") if below else None},
                    "heading": {"text": head.get("value") if head else None}
                }
        except Exception:
            pass

      
        try:
            pix = fz_page.get_pixmap(dpi=150)
            img_name = f"page_{i}.jpg"
            img_path = os.path.join(img_root, img_name)
            pix.save(img_path)
        except Exception:
            pass

        pages_collected.append({
            "text": page_text,
            "tables": tables_rows,
            "page_num": i,
            "images": page_images,
            "items_positional": sorted(page_text_items, key=lambda it: (it.get("bBox", {}).get("y", 0), it.get("bBox", {}).get("x", 0))),
        })

    pdf.close()
    plumber_pdf.close()

    pages = create_comprehensive_pages_structure(pages_collected, filename)

    result = {"pages": pages}

    try:
        output_path = os.path.join("output", f"{filename}.pdf.json")
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "PDF")
    return result
