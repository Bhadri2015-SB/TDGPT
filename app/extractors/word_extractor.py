import json
import os
import time
import pytesseract
import uuid
from PIL import Image
from docx import Document
from docx.table import _Cell
from docx.text.paragraph import Paragraph

# Output image folder (ensure it exists)
OUTPUT_IMG_DIR = "output/images"
os.makedirs(OUTPUT_IMG_DIR, exist_ok=True)

def extract_text_from_paragraphs(paragraphs):
    return "\n".join(p.text.strip() for p in paragraphs if p.text.strip())

def extract_tables_as_text(tables):
    table_texts = []
    for table in tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip().replace('\n', ' ') for cell in row.cells]
            rows.append(" | ".join(cells))
        table_texts.append("\n".join(rows))
    return table_texts

def extract_images(doc):
    """
    Extracts images and runs OCR using pytesseract.
    """
    image_texts = []
    rels = doc.part._rels
    i=1#temporary counter for unique image names
    for rel in rels:
        rel = rels[rel]
        if "image" in rel.target_ref:
            img_ext = rel.target_ref.split('.')[-1]
            image_data = rel.target_part.blob
            unique_name = f"{i}.{img_ext}"#uuid.uuid4()
            i+=1
            image_path = os.path.join(OUTPUT_IMG_DIR, unique_name)
            
            with open(image_path, "wb") as f:
                f.write(image_data)

            # OCR using pytesseract
            try:
                image = Image.open(image_path)
                text = pytesseract.image_to_string(image)
                if text.strip():
                    image_texts.append(text.strip())
            except Exception as e:
                print(f"Error reading OCR from {image_path}: {e}")
    
    return image_texts

def process_word_file(file_path):
    start_time = time.time()
    doc = Document(file_path)
    
    metadata = {
        "file_name": os.path.basename(file_path),
        "file_type": "word",
        "page_count": 1  # python-docx doesn't support real page detection
    }

    text = extract_text_from_paragraphs(doc.paragraphs)
    tables = extract_tables_as_text(doc.tables)
    image_texts = extract_images(doc)

    result = {
        "metadata": metadata,
        "pages": [
            {
                "page_number": 1,
                "text": text,
                "tables": tables,
                "image_paths": image_texts
            }
        ],
        "total_time_taken": f"{time.time() - start_time:.2f} seconds"
    }

    #testing purposes
    with open("output/word_output.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
