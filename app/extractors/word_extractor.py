import json
import os
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any

import aiofiles
from PIL import Image
from docx import Document
import pytesseract

from concurrent.futures import ThreadPoolExecutor

from app.utils.file_handler import change_to_processed

# Constants
OUTPUT_IMG_DIR = Path("output/images")
OUTPUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def extract_text_from_paragraphs(paragraphs) -> str:
    return "\n".join(p.text.strip() for p in paragraphs if p.text.strip())


def extract_tables_as_text(tables) -> List[str]:
    table_texts = []
    for table in tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(" | ".join(cells))
        table_texts.append("\n".join(rows))
    return table_texts


def extract_images_sync(doc: Document, output_dir: Path) -> List[str]:
    """
    Extracts images from the DOCX and runs OCR using pytesseract.
    This function is blocking and should be run in an executor.
    """
    image_texts = []
    rels = doc.part._rels

    for rel in rels.values():
        if "image" in rel.target_ref:
            try:
                img_ext = rel.target_ref.split('.')[-1]
                image_data = rel.target_part.blob
                unique_name = f"{uuid.uuid4()}.{img_ext}"
                image_path = output_dir / unique_name

                with open(image_path, "wb") as f:
                    f.write(image_data)

                image = Image.open(image_path)
                text = pytesseract.image_to_string(image)
                if text.strip():
                    image_texts.append(text.strip())

            except Exception as e:
                logger.warning(f"Failed to process image {rel.target_ref}: {e}")
                return f"Failed to process image in word {rel.target_ref}: {e}"

    return image_texts


async def extract_images(doc: Document, output_dir: Path) -> List[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, extract_images_sync, doc, output_dir)


async def process_word_file(file_path: str) -> Dict[str, Any]:
    """
    Asynchronously processes a Word (.docx) file:
    - Extracts paragraphs, tables, and OCR text from images.
    - Writes output JSON.

    Args:
        file_path (str): Path to the DOCX file.

    Returns:
        dict: Extracted content and metadata.
    """
    start_time = time.time()

    file_name = os.path.basename(file_path)

    loop = asyncio.get_running_loop()
    doc = await loop.run_in_executor(None, Document, file_path)

    metadata = {
        "file_name": file_name,
        "file_type": "word",
        "page_count": 1  # Still estimated due to python-docx limitations
    }

    # Extract textual content
    text = extract_text_from_paragraphs(doc.paragraphs)
    tables = extract_tables_as_text(doc.tables)
    image_texts = await extract_images(doc, OUTPUT_IMG_DIR)

    result = {
        "metadata": metadata,
        "pages": [
            {
                "page_number": 1,
                "text": text,
                "tables": tables,
                "image_data": image_texts
            }
        ],
        "total_time_taken": f"{time.time() - start_time:.2f} seconds"
    }

    print("end of word extractor")

    # Write result to file
    try:
        async with aiofiles.open(f"output/{file_name}.json", "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"Failed to write output JSON: {e}")
        raise
    
    await change_to_processed(str(file_path), "Word")

    return result
