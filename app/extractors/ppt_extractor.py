import os
import io
import time
import json
import aiofiles
from PIL import Image
import pytesseract
from pptx import Presentation
from app.utils.utils import summarize_text
from app.services.image_caption import describe_image
from app.extractors.pdf_extractor import ensure_dirs

async def extract_ppt_content(file_path, groq_client, model):
    start = time.time()
    prs = Presentation(file_path)
    filename = os.path.splitext(os.path.basename(file_path))[0]
    img_root, img_summary_dir, img_vision_dir = ensure_dirs(filename)

    slides = []
    for i, slide in enumerate(prs.slides, start=1):
        texts, images, summaries, visions = [], [], [], []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                texts.append(shape.text.strip())
            if shape.shape_type == 13:
                img_bytes, ext = shape.image.blob, shape.image.ext
                img_name = f"{filename}_slide{i}_img.{ext}"
                img_path = os.path.join(img_root, img_name)

                async with aiofiles.open(img_path, "wb") as f:
                    await f.write(img_bytes)
                images.append(img_path)

                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                ocr_text = pytesseract.image_to_string(pil_img).strip()

                if ocr_text:
                    sum_path = os.path.join(img_summary_dir, f"{filename}_slide{i}_summary.json")
                    async with aiofiles.open(sum_path, "w", encoding="utf-8") as f:
                        await f.write(json.dumps({"ocr_text": ocr_text}, indent=2))
                    summaries.append(sum_path)
                else:
                    desc = await describe_image(img_path, groq_client, model)
                    vis_path = os.path.join(img_vision_dir, f"{filename}_slide{i}_vision.json")
                    async with aiofiles.open(vis_path, "w", encoding="utf-8") as f:
                        await f.write(json.dumps({"description": desc}, indent=2))
                    visions.append(vis_path)

        summary = await summarize_text("\n".join(texts), groq_client, model) if texts else "No text."
        slides.append({
            "slide_number": i,
            "text_blocks": texts,
            "images": images,
            "img_summary_files": summaries,
            "img_vision_files": visions,
            "summary": summary
        })

    return {
        "metadata": {
            "file_name": os.path.basename(file_path),
            "file_type": "pptx",
            "file_size": f"{os.path.getsize(file_path)/1024/1024:.2f} MB",
            "slide_count": len(prs.slides)
        },
        "slides": slides,
        "summary": "PPT processed.",
        "total_time_taken": f"{time.time() - start:.2f} sec"
    }