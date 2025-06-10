import os
import io
import time
import json
import fitz
import aiofiles
from PIL import Image
import pytesseract
from app.utils.utils import summarize_text
from app.services.image_caption import describe_image
from app.core.groq_setup import groq_client, groq_model

def ensure_dirs(base_name):
    img_root = os.path.join("output", "images")
    img_summary = os.path.join(img_root, "img_summary")
    img_vision = os.path.join(img_root, "img_vision")
    os.makedirs(img_summary, exist_ok=True)
    os.makedirs(img_vision, exist_ok=True)
    return img_root, img_summary, img_vision

async def extract_pdf_content(file_path):
    client = groq_client
    model = groq_model
    start = time.time()
    pdf = fitz.open(file_path)
    filename = os.path.splitext(os.path.basename(file_path))[0]
    img_root, img_summary_dir, img_vision_dir = ensure_dirs(filename)  #why "filename" is passed?

    pages = []
    for i, page in enumerate(pdf, start=1):
        text = page.get_text("text").strip()
        image_list = page.get_images(full=True)
        images, summaries, visions = [], [], []

        for idx, img in enumerate(image_list, start=1):
            xref = img[0]
            base_image = pdf.extract_image(xref)
            img_bytes, ext = base_image["image"], base_image["ext"]
            img_name = f"{filename}_page{i}_img{idx}.{ext}"
            img_path = os.path.join(img_root, img_name)

            async with aiofiles.open(img_path, "wb") as f:
                await f.write(img_bytes)
            images.append(img_path)

            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            ocr_text = pytesseract.image_to_string(pil_img).strip()

            if ocr_text:
                summary_path = os.path.join(img_summary_dir, f"{filename}_page{i}_img{idx}_summary.json")
                async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps({"ocr_text": ocr_text}, indent=2))
                summaries.append(summary_path)
            else:
                vision_path = os.path.join(img_vision_dir, f"{filename}_page{i}_img{idx}_vision.json")
                description = await describe_image(img_path)
                async with aiofiles.open(vision_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps({"description": description}, indent=2))
                visions.append(vision_path)

        summary = await summarize_text(text, client, model)
        pages.append({
            "page_number": i,
            "text": text or "No text found.",
            "tables": "No table support in fitz.",
            "images": images,
            "img_summary_files": summaries,
            "img_vision_files": visions,
            "summary": summary,
            "time_taken": f"{time.time() - start:.2f} sec"
        })

    return {
        "metadata": {
            "file_name": os.path.basename(file_path),
            "file_type": "pdf",
            "file_size": f"{os.path.getsize(file_path)/(1024*1024):.2f} MB",
            "page_count": len(pdf)
        },
        "pages": pages,
        "overall_summary": "PDF extraction complete.",
        "total_time_taken": f"{time.time() - start:.2f} sec"
    }
