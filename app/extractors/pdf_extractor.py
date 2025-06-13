import os
import io
import time
import json
import fitz
import aiofiles
import pdfplumber
from PIL import Image
import pytesseract
from app.utils.file_handler import change_to_processed
from app.services.image_caption import describe_image
from app.core.groq_setup import groq_client, groq_model
from app.core.logger import app_logger


async def ensure_dirs():
    img_root = os.path.join("output", "images")
    img_summary = os.path.join(img_root, "img_summary")
    img_vision = os.path.join(img_root, "img_vision")
    os.makedirs(img_summary, exist_ok=True)
    os.makedirs(img_vision, exist_ok=True)
    return img_root, img_summary, img_vision


async def extract_pdf_content(file_path):
    start_time = time.time()
    filename = os.path.splitext(os.path.basename(file_path))[0]
    img_root, img_summary_dir, img_vision_dir = await ensure_dirs()

    app_logger.info(f"Starting PDF extraction: {file_path}")

    try:
        pdf = fitz.open(file_path)
        plumber_pdf = pdfplumber.open(file_path)
        app_logger.debug(f"Opened PDF with {len(pdf)} pages")
    except Exception as e:
        app_logger.exception(f"Failed to open PDF file: {e}")
        raise RuntimeError(f"Failed to open PDF: {e}")

    pages = []

    for i, (fitz_page, plumber_page) in enumerate(zip(pdf, plumber_pdf.pages), start=1):
        app_logger.info(f"Processing page {i}")
        text = fitz_page.get_text("text").strip()
        image_list = fitz_page.get_images(full=True)
        app_logger.debug(f"Found {len(image_list)} images on page {i}")

        images, summaries, visions = [], [], []

        for idx, img in enumerate(image_list, start=1):
            xref = img[0]
            base_image = pdf.extract_image(xref)
            img_bytes, ext = base_image["image"], base_image["ext"]
            img_name = f"{filename}_page{i}_img{idx}.{ext}"
            img_path = os.path.join(img_root, img_name)

            try:
                async with aiofiles.open(img_path, "wb") as f:
                    await f.write(img_bytes)
                app_logger.debug(f"Saved image: {img_name}")
                images.append(img_path)

                pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                ocr_text = pytesseract.image_to_string(pil_img).strip()

                if ocr_text:
                    summary = {"ocr_text": ocr_text}
                    summaries.append(summary)
                    summary_path = os.path.join(img_summary_dir, f"{filename}_page{i}_img{idx}_summary.json")
                    async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
                        await f.write(json.dumps(summary, indent=2))
                    app_logger.debug(f"OCR saved for: {img_name}")
                else:
                    description = await describe_image(img_path)
                    vision = {"description": description}
                    visions.append(vision)
                    vision_path = os.path.join(img_vision_dir, f"{filename}_page{i}_img{idx}_vision.json")
                    async with aiofiles.open(vision_path, "w", encoding="utf-8") as f:
                        await f.write(json.dumps(vision, indent=2))
                    app_logger.warning(f"OCR empty for {img_name}, fallback to vision description")
            except Exception as e:
                app_logger.exception(f"Error processing image {img_name}: {e}")
                continue

        try:
            tables_raw = plumber_page.extract_tables()
            extracted_tables = []
            for table in tables_raw:
                if table:
                    extracted_tables.append({
                        "headers": table[0],
                        "rows": table[1:]
                    })
            app_logger.debug(f"Extracted {len(extracted_tables)} tables from page {i}")
        except Exception as e:
            app_logger.exception(f"Error extracting tables from page {i}: {e}")
            extracted_tables = []

        pages.append({
            "page_number": i,
            "text": text or "No text found.",
            "tables": extracted_tables if extracted_tables else "No tables found.",
            "images": images,
            "img_summary_files": summaries,
            "img_vision_files": visions,
            "time_taken": f"{time.time() - start_time:.2f} sec"
        })

    pdf.close()
    plumber_pdf.close()

    result = {
        "metadata": {
            "file_name": os.path.basename(file_path),
            "file_type": "pdf",
            "file_size": f"{os.path.getsize(file_path) / (1024 * 1024):.2f} MB",
            "page_count": len(pages)
        },
        "pages": pages,
        "overall_summary": "PDF extraction complete.",
        "total_time_taken": f"{time.time() - start_time:.2f} sec"
    }

    try:
        output_path = os.path.join("output", f"{filename}.json")
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
        app_logger.info(f"Extraction result saved to: {output_path}")
    except Exception as e:
        app_logger.exception(f"Failed to write JSON output: {e}")
        raise IOError(f"Failed to write JSON output file: {e}")

    await change_to_processed(str(file_path), "PDF")
    app_logger.info(f"Finished processing PDF: {file_path}")

    return result
