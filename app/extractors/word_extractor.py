import os
import json
import uuid
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any

import aiofiles
from PIL import Image
from docx import Document
import pytesseract

from app.utils.file_handler import change_to_processed

# Output directory for extracted images
OUTPUT_IMG_DIR = Path("output/images")
OUTPUT_IMG_DIR.mkdir(parents=True, exist_ok=True)


def extract_text_from_paragraphs(paragraphs) -> str:
    """Extracts and joins non-empty paragraph texts."""
    return "\n".join(p.text.strip() for p in paragraphs if p.text.strip())


def extract_tables_as_text(tables) -> List[str]:
    """Extracts table contents row-by-row into readable string format."""
    table_texts = []
    for table in tables:
        rows = [
            " | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells)
            for row in table.rows
        ]
        table_texts.append("\n".join(rows))
    return table_texts


def extract_images_sync(doc: Document, output_dir: Path) -> List[str]:
    """
    Extracts images from the DOCX file and applies OCR to each.
    Should be run in a background thread via executor.
    """
    image_texts = []
    rels = doc.part._rels

    for rel in rels.values():
        if "image" in rel.target_ref:
            try:
                extension = rel.target_ref.split('.')[-1]
                image_data = rel.target_part.blob
                file_name = f"{uuid.uuid4()}.{extension}"
                image_path = output_dir / file_name

                with open(image_path, "wb") as f:
                    f.write(image_data)

                image = Image.open(image_path).convert("RGB")
                text = pytesseract.image_to_string(image).strip()

                if text:
                    image_texts.append(text)
            except Exception:
                # Skip corrupt image silently in production context
                continue

    return image_texts


async def extract_images_async(doc: Document, output_dir: Path) -> List[str]:
    """Runs image extraction in a background thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, extract_images_sync, doc, output_dir)


async def process_word_file(file_path: str) -> Dict[str, Any]:
    """
    Asynchronously processes a Word (.docx) file:
    - Extracts paragraphs, tables, and OCR from embedded images.
    - Saves result to a JSON file.
    
    Args:
        file_path (str): Path to the .docx file.
    
    Returns:
        dict: Structured document data with metadata.
    """
    start_time = time.time()
    file_name = os.path.basename(file_path)
    doc = await asyncio.get_running_loop().run_in_executor(None, Document, file_path)

    # Extract textual content
    text = extract_text_from_paragraphs(doc.paragraphs)
    tables = extract_tables_as_text(doc.tables)
    image_texts = await extract_images_async(doc, OUTPUT_IMG_DIR)

    result = {
        "metadata": {
            "file_name": file_name,
            "file_type": "word",
            "page_count": 1  # Estimated; .docx doesn't provide page count
        },
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

    output_path = Path("output") / f"{file_name}.json"
    try:
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        raise IOError(f"Failed to write output JSON: {e}")

    await change_to_processed(file_path, "Word")
    return result
