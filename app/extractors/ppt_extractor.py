import io
import time
import json
from pathlib import Path
from typing import Dict, Any

import aiofiles
from PIL import Image
import pytesseract
from pptx import Presentation

from app.utils.file_handler import change_to_processed
from app.utils.utils import summarize_text
from app.services.image_caption import describe_image
from app.extractors.pdf_extractor import ensure_dirs
from app.core.groq_setup import groq_client, groq_model


async def extract_ppt_content(file_path: str) -> Dict[str, Any]:
    """
    Extracts text and image content from a PowerPoint file.
    Applies OCR or visual description to images and stores outputs.
    
    Args:
        file_path (str): Path to the .pptx file.
    
    Returns:
        dict: Extraction result with slide metadata and processing info.
    """
    client = groq_client
    model = groq_model
    start_time = time.time()

    file = Path(file_path)
    filename = file.stem
    output_dirs = ensure_dirs(filename)

    try:
        prs = Presentation(str(file))
    except Exception as e:
        return {
            "file_name": file.name,
            "file_type": "pptx",
            "status": "error",
            "message": f"Failed to open PowerPoint file: {e}"
        }

    slides_data = []

    for i, slide in enumerate(prs.slides, start=1):
        text_blocks = []
        images, summary_files, vision_files = [], [], []

        for shape in slide.shapes:
            # Extract text
            if hasattr(shape, "text") and shape.text.strip():
                text_blocks.append(shape.text.strip())

            # Extract image if shape is a picture (type 13)
            if shape.shape_type == 13:
                try:
                    img_bytes = shape.image.blob
                    ext = shape.image.ext
                    img_name = f"{filename}_slide{i}_img.{ext}"
                    img_path = output_dirs["img_root"] / img_name

                    async with aiofiles.open(img_path, "wb") as f:
                        await f.write(img_bytes)

                    images.append(str(img_path))

                    pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    ocr_text = pytesseract.image_to_string(pil_img).strip()

                    if ocr_text:
                        summary_path = output_dirs["img_summary"] / f"{filename}_slide{i}_summary.json"
                        async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
                            await f.write(json.dumps({"ocr_text": ocr_text}, indent=2))
                        summary_files.append(str(summary_path))
                    else:
                        vision_desc = await describe_image(str(img_path))
                        vision_path = output_dirs["img_vision"] / f"{filename}_slide{i}_vision.json"
                        async with aiofiles.open(vision_path, "w", encoding="utf-8") as f:
                            await f.write(json.dumps({"description": vision_desc}, indent=2))
                        vision_files.append(str(vision_path))

                except Exception as e:
                    vision_files.append(f"Image extraction failed: {e}")

        # Optional: enable summarization here
        # summary = await summarize_text("\n".join(text_blocks), client, model) if text_blocks else "No text."

        slides_data.append({
            "slide_number": i,
            "text_blocks": text_blocks,
            "images": images,
            "img_summary_files": summary_files,
            "img_vision_files": vision_files,
            # "summary": summary
        })

    result = {
        "metadata": {
            "file_name": file.name,
            "file_type": "pptx",
            "file_size": f"{file.stat().st_size / (1024 * 1024):.2f} MB",
            "slide_count": len(prs.slides)
        },
        "slides": slides_data,
        "summary": "PPT processed.",
        "total_time_taken": f"{time.time() - start_time:.2f} sec"
    }

    print("end of ppt extractor")

    try:
        output_file = Path("output") / f"{filename}.json"
        async with aiofiles.open(output_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file), "PPT")
    return result
