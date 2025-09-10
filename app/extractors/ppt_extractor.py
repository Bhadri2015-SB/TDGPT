import os
import io
import time
import json
import re
import aiofiles
import subprocess
import fitz
import pdfplumber
from PIL import Image as PILImage
import pytesseract
from typing import List, Optional
from pptx import Presentation

from app.utils.file_handler import change_to_processed
from app.extractors.pdf_extractor import (
    ensure_dirs as ensure_img_dirs,
    create_comprehensive_pages_structure,
    create_markdown_from_text,
)


async def is_legacy_ppt(file_path: str) -> bool:
    return file_path.lower().endswith(".ppt") and not file_path.lower().endswith(".pptx")


def convert_pptx_to_pdf_via_office(pptx_path: str) -> Optional[str]:
    try:
        import win32com.client  # type: ignore
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = True
        presentation = app.Presentations.Open(os.path.abspath(pptx_path), WithWindow=False)
        pdf_dir = os.path.join("output", "tmp_pdf")
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, f"{os.path.splitext(os.path.basename(pptx_path))[0]}.pdf")
        presentation.SaveAs(os.path.abspath(pdf_path), 32)  # 32 = ppSaveAsPDF
        presentation.Close()
        app.Quit()
        return pdf_path
    except Exception:
        return None


def convert_ppt_to_pptx(ppt_path: str) -> Optional[str]:
    output_dir = os.path.dirname(ppt_path)
    try:
        subprocess.run([
            "libreoffice", "--headless", "--convert-to", "pptx", "--outdir", output_dir, ppt_path
        ], check=True)
        new_path = ppt_path.replace(".ppt", ".pptx")
        return new_path if os.path.exists(new_path) else None
    except Exception:
        return None


def convert_pptx_to_pdf_via_libreoffice(pptx_path: str) -> Optional[str]:
    try:
        out_dir = os.path.join("output", "tmp_pdf")
        os.makedirs(out_dir, exist_ok=True)
        subprocess.run([
            "libreoffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, pptx_path
        ], check=True)
        pdf_path = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(pptx_path))[0]}.pdf")
        return pdf_path if os.path.exists(pdf_path) else None
    except Exception:
        return None


def _cy(b):
    return float(b.get("y", 0)) + float(b.get("h", 0)) / 2.0


async def extract_ppt_content(file_path):
    start = time.time()

    filename = os.path.splitext(os.path.basename(file_path))[0]
    img_root, _, _ = await ensure_img_dirs()

    # Try to normalize to PPTX if legacy
    if await is_legacy_ppt(file_path):
        pptx_path = convert_ppt_to_pptx(file_path)
        if not pptx_path:
            return {"error": "Failed to convert .ppt to .pptx"}
        file_path = pptx_path

    # Convert PPTX -> PDF
    pdf_path = convert_pptx_to_pdf_via_office(file_path) or convert_pptx_to_pdf_via_libreoffice(file_path)

    pages_collected: List[dict] = []

    if pdf_path and os.path.exists(pdf_path):
        # Use the same PDF pipeline to produce uniform positional data
        try:
            pdf = fitz.open(pdf_path)
            plumber_pdf = pdfplumber.open(pdf_path)
        except Exception as e:
            return {"error": f"Failed to open converted PDF: {e}"}

        # Configure tesseract on Windows (best-effort)
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

        for i, (fz_page, pl_page) in enumerate(zip(pdf, plumber_pdf.pages), start=1):
            page_text = (fz_page.get_text("text") or "").strip()

            # Tables
            tables_rows: List[List[List[str]]] = []
            try:
                tables_raw = pl_page.extract_tables() or []
                for t in tables_raw:
                    if t and any(any(cell for cell in row) for row in t):
                        tables_rows.append([["" if cell is None else str(cell).strip() for cell in row] for row in t])
            except Exception:
                pass

            # Text items + image blocks
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
                            w = float(x1 - x0); h = float(y1 - y0)
                            lvl = None; item_type = "text"
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

            # Inline images with OCR and anchors
            page_images: List[dict] = []
            try:
                image_blocks_sorted = sorted(image_blocks, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
                for img_idx, blk in enumerate(image_blocks_sorted, start=1):
                    rect = fitz.Rect(blk["bbox"])
                    try:
                        pix = fz_page.get_pixmap(dpi=150, clip=rect)
                        img_name = f"img_p{i}_{img_idx}.png"
                        img_path = os.path.join(img_root, img_name)
                        pix.save(img_path)

                        # OCR words
                        ocr_items = []
                        try:
                            pil_img = PILImage.open(img_path).convert("RGB")
                            data = pytesseract.image_to_data(
                                pil_img, lang="eng", config="--oem 3 --psm 6", output_type=pytesseract.Output.DICT
                            )
                            n = len(data.get("text", []))
                            for j in range(n):
                                txt = (data["text"][j] or "").strip()
                                if not txt:
                                    continue
                                try:
                                    conf = float(data.get("conf", ["-1"])[j])
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
                            "height": pix.height,
                            "width": pix.width,
                            "x": float(rect.x0),
                            "y": float(rect.y0),
                            "original_width": pix.width,
                            "original_height": pix.height,
                            "ocr": ocr_items,
                            "type": "inline_image",
                        })
                    except Exception:
                        continue
            except Exception:
                pass

            # Anchors
            try:
                text_items_sorted = sorted(
                    [ti for ti in page_text_items if ti.get("type") in ("text", "heading") and ti.get("bBox")],
                    key=lambda t: _cy(t["bBox"]) )
                for img in page_images:
                    ib = {"x": img.get("x", 0), "y": img.get("y", 0), "w": img.get("width", 0), "h": img.get("height", 0)}
                    icy = _cy(ib)
                    above = None; below = None; head = None
                    for ti in text_items_sorted:
                        tcy = _cy(ti["bBox"]) 
                        if tcy <= icy:
                            above = ti
                        elif tcy > icy and below is None:
                            below = ti
                    headings = [ti for ti in text_items_sorted if ti.get("type") == "heading"]
                    if headings:
                        head = min(headings, key=lambda h: abs(_cy(h["bBox"]) - icy))
                    img["anchors"] = {
                        "above_text": {"text": above.get("value") if above else None},
                        "below_text": {"text": below.get("value") if below else None},
                        "heading": {"text": head.get("value") if head else None}
                    }
            except Exception:
                pass

            # Full-page screenshot
            try:
                pix = fz_page.get_pixmap(dpi=150)
                page_img_name = f"page_{i}.jpg"
                page_img_path = os.path.join(img_root, page_img_name)
                pix.save(page_img_path)
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
    else:
        # Fallback: parse with python-pptx (no coordinates). Produce at least the same schema.
        try:
            prs = Presentation(file_path)
        except Exception as e:
            return {"error": f"Failed to open PPTX: {e}"}

        pages: List[dict] = []
        y_base = 72.0
        for i, slide in enumerate(prs.slides, start=1):
            texts: List[str] = []
            images: List[dict] = []
            y_cursor = y_base
            img_idx = 0
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text and shape.text.strip():
                    texts.append(shape.text.strip())
                # Picture
                try:
                    if getattr(shape, "shape_type", None) == 13 and getattr(shape, "image", None):
                        img_idx += 1
                        img_bytes, ext = shape.image.blob, shape.image.ext
                        img_name = f"img_p{i}_{img_idx}.{ext}"
                        img_path = os.path.join(img_root, img_name)
                        async with aiofiles.open(img_path, "wb") as f:
                            await f.write(img_bytes)
                        try:
                            with PILImage.open(io.BytesIO(img_bytes)) as pil:
                                w, h = pil.size
                        except Exception:
                            w, h = (400, 300)
                        images.append({
                            "name": img_name,
                            "height": h,
                            "width": w,
                            "x": 72.0,
                            "y": y_cursor,
                            "original_width": w,
                            "original_height": h,
                            "type": "inline_image",
                        })
                        y_cursor += h + 20
                except Exception:
                    continue

            page_text = "\n\n".join(texts)
            md_content = create_markdown_from_text(page_text)

            page = {
                "page": i,
                "text": f"{page_text}\n\n{i}",
                "md": f"{md_content}\n\n{i}\n",
                "images": images + [{
                    "name": f"page_{i}.jpg",
                    "height": 841.889763779528,
                    "width": 595.303937007874,
                    "x": 0,
                    "y": 0,
                    "original_width": 2263,
                    "original_height": 3200,
                    "type": "full_page_screenshot",
                }],
                "charts": [],
                "items": [],
                "status": "OK",
                "originalOrientationAngle": 0,
                "links": [],
                "width": 595.303937007874,
                "height": 841.889763779528,
                "triggeredAutoMode": False,
                "parsingMode": "premium",
                "structuredData": None,
                "noStructuredContent": False,
                "noTextContent": len(page_text.strip()) == 0,
                "pageHeaderMarkdown": "",
                "pageFooterMarkdown": f"\n{i}\n",
                "confidence": 0.99,
            }
            pages.append(page)
        result = {"pages": pages}

    output_path = os.path.join("output", f"{filename}.pptx.json")
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "PPT")
    return result
