import io
import time
import json
from pathlib import Path
from typing import Dict, Any

import aiofiles
import fitz
from PIL import Image
import pytesseract

from app.utils.file_handler import change_to_processed
from app.utils.utils import summarize_text
from app.services.image_caption import describe_image
from app.core.groq_setup import groq_client, groq_model


def ensure_output_dirs() -> Dict[str, Path]:
    """Ensure necessary image output directories exist."""
    base_dir = Path("output/images")
    summary_dir = base_dir / "img_summary"
    vision_dir = base_dir / "img_vision"
    summary_dir.mkdir(parents=True, exist_ok=True)
    vision_dir.mkdir(parents=True, exist_ok=True)
    return {
        "img_root": base_dir,
        "img_summary": summary_dir,
        "img_vision": vision_dir,
    }


async def extract_pdf_content(file_path: str) -> Dict[str, Any]:
    """
    Extracts text and images from a PDF file, applies OCR or image description, and saves the result.

    Args:
        file_path (str): Path to the PDF file.

    Returns:
        dict: Structured result with metadata, page-wise content, and image analyses.
    """
    client = groq_client
    model = groq_model
    start_time = time.time()
    file = Path(file_path)
    filename = file.stem

    output_dirs = ensure_output_dirs()

    try:
        pdf = fitz.open(str(file))
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "pdf",
            "status": "error",
            "message": f"Failed to open PDF: {e}"
        }

    pages = []

    for i, page in enumerate(pdf, start=1):
        page_text = page.get_text("text").strip()
        image_list = page.get_images(full=True)

        images, summary_files, vision_files = [], [], []

        for idx, img in enumerate(image_list, start=1):
            try:
                xref = img[0]
                base_image = pdf.extract_image(xref)
                img_bytes = base_image["image"]
                ext = base_image["ext"]
                image_filename = f"{filename}_page{i}_img{idx}.{ext}"
                image_path = output_dirs["img_root"] / image_filename

                async with aiofiles.open(image_path, "wb") as f:
                    await f.write(img_bytes)

                images.append(str(image_path))

                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                ocr_text = pytesseract.image_to_string(pil_img).strip()

                if ocr_text:
                    summary_file = output_dirs["img_summary"] / f"{filename}_page{i}_img{idx}_summary.json"
                    async with aiofiles.open(summary_file, "w", encoding="utf-8") as f:
                        await f.write(json.dumps({"ocr_text": ocr_text}, indent=2))
                    summary_files.append(str(summary_file))
                else:
                    vision_file = output_dirs["img_vision"] / f"{filename}_page{i}_img{idx}_vision.json"
                    description = await describe_image(str(image_path))
                    async with aiofiles.open(vision_file, "w", encoding="utf-8") as f:
                        await f.write(json.dumps({"description": description}, indent=2))
                    vision_files.append(str(vision_file))
            except Exception as e:
                vision_files.append(f"Image processing failed: {e}")

        pages.append({
            "page_number": i,
            "text": page_text or "No text found.",
            "tables": "No table support in fitz.",
            "images": images,
            "img_summary_files": summary_files,
            "img_vision_files": vision_files,
            "time_taken": f"{time.time() - start_time:.2f} sec"
        })

    result = {
        "metadata": {
            "file_name": file.name,
            "file_type": "pdf",
            "file_size": f"{file.stat().st_size / (1024 * 1024):.2f} MB",
            "page_count": len(pdf)
        },
        "pages": pages,
        "overall_summary": "PDF extraction complete.",
        "total_time_taken": f"{time.time() - start_time:.2f} sec"
    }

    pdf.close()

    try:
        output_file = Path("output") / f"{filename}.json"
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file), "PDF")
    return result
