import os
import time
import json
import io
import re
import aiofiles
import pytesseract
from typing import List, Optional
from docx import Document
from PIL import Image
import docx2txt
from app.utils.file_handler import change_to_processed 


async def ensure_dirs():
    """Ensure required directories exist"""
    img_root = "output/images/"
    img_summary_dir = os.path.join(img_root, "summary")
    img_vision_dir = os.path.join(img_root, "vision")
    
    for dir_path in [img_root, img_summary_dir, img_vision_dir]:
        os.makedirs(dir_path, exist_ok=True)
        
    return img_root, img_summary_dir, img_vision_dir
 

def create_markdown_from_text(text):
    """Convert text to markdown format with proper formatting"""
    if not text.strip():
        return ""
    
    lines = text.split('\n')
    markdown_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            markdown_lines.append("")
        elif re.match(r'^\d+\.\d+(?:\.\d+)*\s+\S+', line):
            markdown_lines.append(f"### {line}")
        elif re.match(r'^\d+\.?\s+\S+', line):
            markdown_lines.append(f"## {line}")
        elif len(line) < 50 and line.isupper() and len(line) > 3:
            markdown_lines.append(f"# {line}")
        else:
            markdown_lines.append(line)
        
        i += 1
    
    return '\n'.join(markdown_lines)


def create_html_table_from_data(table_data):
    """Create HTML table exactly like the original format"""
    if not table_data or len(table_data) == 0:
        return ""
    
    html = "\n<table>\n<thead>\n<tr>\n"
    
    if len(table_data) > 0:
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


def extract_images_from_docx(doc, filename, img_root):
    """Extract all images from DOCX document and save them with position tracking"""
    images_info = []
    image_counter = 1
    
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            try:
                image_part = rel.target_part
                image_data = image_part.blob
                
                image_format = "png"
                if image_part.content_type == "image/jpeg":
                    image_format = "jpg"
                elif image_part.content_type == "image/gif":
                    image_format = "gif"
                
                image_filename = f"{filename}_img_{image_counter}.{image_format}"
                image_path = os.path.join(img_root, image_filename)
                
                with open(image_path, 'wb') as img_file:
                    img_file.write(image_data)
                
                try:
                    with Image.open(io.BytesIO(image_data)) as img:
                        width, height = img.size
                except:
                    width, height = 400, 300  # Default dimensions
                
                image_info = {
                    "name": image_filename,
                    "height": height,
                    "width": width,
                    "x": 72.0,  # Default left margin
                    "y": 100.0 + (image_counter * 50),  # Distribute vertically
                    "original_width": width,
                    "original_height": height,
                    "path": image_path,
                    "type": "extracted_image"
                }
                
                images_info.append(image_info)
                image_counter += 1
                
            except Exception as e:
                print(f"Error extracting image: {e}")
                continue
    
    return images_info


def extract_page_content_with_structure(doc, filename, img_root):
    """Extract content from Word document maintaining page structure and order"""
    pages = []
    current_page_content = []
    current_page_tables = []
    page_break_indicators = [
        '\f',  # Form feed character
        '\x0c',  # Page break character
        'Page Break',
        '---PAGE---'
    ]
    
    all_images = extract_images_from_docx(doc, filename, img_root)
    
    paragraph_count = 0
    char_count = 0
    max_chars_per_page = 2000  # Realistic page character limit
    max_paragraphs_per_page = 20  # Realistic paragraph limit
    
    for i, para in enumerate(doc.paragraphs):
        para_text = para.text.strip()
        
        is_page_break = any(indicator in para_text for indicator in page_break_indicators)
        
        is_natural_break = (
            char_count > max_chars_per_page or 
            paragraph_count > max_paragraphs_per_page or
            (para_text and para_text.isdigit() and len(para_text) < 3)  # Page numbers
        )
        
        if is_page_break or (is_natural_break and current_page_content):
            if current_page_content:
                page_text = '\n'.join(current_page_content)
                pages.append({
                    'text': page_text,
                    'tables': current_page_tables.copy(),
                    'page_num': len(pages) + 1,
                    'images': []  # Will be distributed later
                })
                current_page_content = []
                current_page_tables = []
                paragraph_count = 0
                char_count = 0
        
        if para_text and not is_page_break:
            current_page_content.append(para_text)
            char_count += len(para_text)
            paragraph_count += 1
    
    if current_page_content:
        page_text = '\n'.join(current_page_content)
        pages.append({
            'text': page_text,
            'tables': current_page_tables.copy(),
            'page_num': len(pages) + 1,
            'images': []
        })
    
    for table in doc.tables:
        table_data = []
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                row_data.append(cell.text.strip())
            if any(cell for cell in row_data):  # Only add non-empty rows
                table_data.append(row_data)
        
        if table_data:
            table_text = ' '.join([' '.join(row) for row in table_data[:2]])  # First 2 rows for matching
            
            for page_data in pages:
                if any(cell in page_data['text'] for row in table_data[:2] for cell in row if cell):
                    page_data['tables'].append(table_data)
                    break
    
    if pages and all_images:
        images_per_page = len(all_images) // len(pages)
        remaining_images = len(all_images) % len(pages)
        
        image_index = 0
        for i, page_data in enumerate(pages):
            page_image_count = images_per_page + (1 if i < remaining_images else 0)
            page_data['images'] = all_images[image_index:image_index + page_image_count]
            image_index += page_image_count
    
    return pages


def split_text_into_pages_advanced(text):
    """Advanced page splitting for text-based extraction (fallback)"""
    if not text.strip():
        return ["No content available."]
    
    page_patterns = [
        r'\n\s*\d+\s*\n',  # Page numbers
        r'\nPage\s+\d+',   # "Page X" patterns
        r'\n\s*[─━-]{10,}\s*\n',  # Horizontal lines
    ]
    
    pages = []
    current_text = text
    
    for pattern in page_patterns:
        splits = re.split(pattern, current_text, flags=re.IGNORECASE)
        if len(splits) > 1:
            pages = [s.strip() for s in splits if s.strip()]
            break
    
    if not pages:
        paragraphs = text.split('\n\n')
        current_page = ""
        page_length_limit = 2000
        
        for paragraph in paragraphs:
            if len(current_page) + len(paragraph) > page_length_limit and current_page:
                pages.append(current_page.strip())
                current_page = paragraph
            else:
                current_page += "\n\n" + paragraph if current_page else paragraph
        
        if current_page.strip():
            pages.append(current_page.strip())
    
    return pages if pages else ["No content available."]


def create_comprehensive_items(text):
    """Create comprehensive items array from text with proper formatting - Enhanced version"""
    if not text.strip():
        return []
    
    items = []
    lines = text.split('\n')
    y_position = 72.0
    current_paragraph = []
    
    for line in lines:
        line = line.strip()
        if not line:
            if current_paragraph:
                para_text = '\n'.join(current_paragraph)
                item = create_item_from_text(para_text, y_position)
                items.append(item)
                y_position += item["bBox"]["h"] + 10
                current_paragraph = []
            continue
        
        if (line.isupper() and len(line) < 50) or \
           re.match(r'^\d+\.?\s+[A-Z]', line) or \
           line.startswith(('Table', 'Figure', 'Chart')):
            if current_paragraph:
                para_text = '\n'.join(current_paragraph)
                item = create_item_from_text(para_text, y_position)
                items.append(item)
                y_position += item["bBox"]["h"] + 10
                current_paragraph = []
            
            item = create_item_from_text(line, y_position)
            items.append(item)
            y_position += item["bBox"]["h"] + 10
        else:
            current_paragraph.append(line)
    
    if current_paragraph:
        para_text = '\n'.join(current_paragraph)
        item = create_item_from_text(para_text, y_position)
        items.append(item)
    
    return items


def create_item_from_text(text, y_position):
    """Create a structured item from text content"""
    text = text.strip()
    
    item_type = "text"
    level = None
    
    if re.match(r'^\d+\.\d+(?:\.\d+)*\s+\S+', text):
        item_type = "heading"
        level = 3
    elif re.match(r'^\d+\.?\s+\S+', text):
        item_type = "heading"
        level = 2
    elif text.isupper() and len(text) < 50 and len(text) > 3:
        item_type = "heading"
        level = 1
    
    if '|' in text and text.count('|') >= 2:
        item_type = "table"
        rows = []
        for line in text.split('\n'):
            if '|' in line:
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                if cells:
                    rows.append(cells)
        
        table_item = {
            "type": "table",
            "rows": rows,
            "html": create_table_html(rows),
            "md": create_table_markdown(rows),
            "isPerfectTable": True,
            "csv": create_table_csv(rows),
            "bBox": {
                "x": 72.8,
                "y": y_position,
                "w": 449.8,
                "h": 20 + (len(rows) * 25)
            }
        }
        return table_item
    
    height = 12 + (len(text.split('\n')) * 14)
    width = min(449.8, len(text) * 7)  # Approximate width
    
    item = {
        "type": item_type,
        "value": text,
        "md": create_markdown_from_text(text),
        "bBox": {
            "x": 72.8,
            "y": y_position,
            "w": width,
            "h": height
        }
    }
    
    if level:
        item["lvl"] = level
    
    return item


def create_table_html(rows):
    """Create HTML table from rows"""
    if not rows:
        return "<table></table>"
    
    html = "<table>\n"
    if len(rows) > 1:
        html += "<thead>\n<tr>\n"
        for cell in rows[0]:
            html += f"<th>{cell}</th>\n"
        html += "</tr>\n</thead>\n"
        
        html += "<tbody>\n"
        for row in rows[1:]:
            html += "<tr>\n"
            for cell in row:
                html += f"<td>{cell}</td>\n"
            html += "</tr>\n"
        html += "</tbody>\n"
    else:
        html += "<tr>\n"
        for cell in rows[0]:
            html += f"<td>{cell}</td>\n"
        html += "</tr>\n"
    
    html += "</table>"
    return html


def create_table_markdown(rows):
    """Create Markdown table from rows"""
    if not rows:
        return ""
    
    if len(rows) == 1:
        return "| " + " | ".join(rows[0]) + " |"
    
    md = "| " + " | ".join(rows[0]) + " |\n"
    md += "| " + " | ".join(["-" * len(cell) for cell in rows[0]]) + " |\n"
    for row in rows[1:]:
        md += "| " + " | ".join(row) + " |\n"
    
    return md.strip()


def create_table_csv(rows):
    """Create CSV from rows with all fields quoted for stability."""
    import io, csv
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator='\n')
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    return buf.getvalue().replace('\r\n', '\n').rstrip("\n")


def create_table_plain_text(rows):
    """Render a table (list of rows) into aligned plain text columns for inclusion in page.text."""
    if not rows:
        return ""
    num_cols = max(len(r) for r in rows)
    col_widths = [0] * num_cols
    for r in rows:
        for i, cell in enumerate(r):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    lines = []
    for r in rows:
        cells = []
        for i in range(num_cols):
            val = "" if i >= len(r) or r[i] is None else str(r[i])
            cells.append(val.ljust(col_widths[i]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


async def extract_doc_content_comprehensive(file_path):
    """Extract content from legacy .doc files using multiple methods"""
    try:
        try:
            text = docx2txt.process(file_path)
            if text and len(text.strip()) > 100:
                ascii_ratio = sum(1 for c in text if ord(c) < 128) / len(text) if text else 0
                word_ratio = len(re.findall(r'\b[a-zA-Z]{3,}\b', text)) / len(text.split()) if text.split() else 0
                
                if ascii_ratio > 0.8 and word_ratio > 0.3:
                    return text
        except:
            pass
        
        with open(file_path, 'rb') as f:
            content = f.read()
        
        readable_parts = []
        
        for encoding in ['utf-8', 'utf-16le', 'latin-1', 'cp1252']:
            try:
                decoded = content.decode(encoding, errors='ignore')
                
                sentences = re.findall(r'[A-Z][a-z\s,.\'\-]{20,}[.!?]', decoded)
                paragraphs = re.findall(r'[A-Z][a-zA-Z0-9\s,.\'\-\(\)]{50,}', decoded)
                
                readable_parts.extend(sentences[:10])
                readable_parts.extend(paragraphs[:10])
                
            except:
                continue
        
        if readable_parts:
            meaningful_text = '\n\n'.join(set(readable_parts))  # Remove duplicates
            if len(meaningful_text) > 300:
                return meaningful_text
        
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            extracted_text = ""
            
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'utf-16le']:
                try:
                    decoded = content.decode(encoding, errors='ignore')
                    
                    text_blocks = re.findall(r'[A-Za-z][A-Za-z0-9\s.,;:!?\'"()\-]{30,}', decoded)
                    if text_blocks:
                        extracted_text += '\n'.join(text_blocks[:20])  # Limit to avoid too much noise
                        break
                except:
                    continue
            
            if extracted_text and len(extracted_text.strip()) > 50:
                return extracted_text.strip()
                
        except Exception as e:
            pass
        
        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        
        return f"""Document: {filename}
File Size: {file_size:,} bytes
Format: Legacy Microsoft Word (.doc)

Note: This is a legacy binary format document that requires specialized processing.
The document content could not be extracted using standard text extraction methods.

Recommendations:
1. Open the file in Microsoft Word
2. Save as Word Document (.docx) format  
3. Re-upload for enhanced text extraction

Alternative: Convert to PDF format for better text extraction compatibility."""

    except Exception as e:
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        filename = os.path.basename(file_path) if os.path.exists(file_path) else 'Unknown'
        
        return f"""Document Processing Error

File: {filename}
Size: {file_size:,} bytes
Error: {str(e)}

This document encountered processing difficulties.
Please try converting to .docx format for better extraction results."""


def create_single_page_structure(text, page_number=1, images_list=None):
    """Create a single page structure matching the JSON format specification"""
    if images_list is None:
        images_list = []
    
    items = create_comprehensive_items(text)
    
    md_content = create_markdown_from_text(text)
    if not md_content.strip().endswith(str(page_number)):
        md_content = f"{md_content}\n\n{page_number}\n"
    
    page_images = images_list.copy()
    page_images.append({
        "name": f"page_{page_number}.jpg",
        "height": 841.889763779528,
        "width": 595.303937007874,
        "x": 0,
        "y": 0,
        "original_width": 2263,
        "original_height": 3200,
        "type": "full_page_screenshot"
    })
    
    lines = text.split('\n')
    page_header = ""
    page_footer = ""
    
    if lines and len(lines[0].strip()) < 50 and not lines[0].strip().startswith(('1.', '2.', '3.')):
        page_header = lines[0].strip()
    if lines and len(lines) > 3 and lines[-1].strip().isdigit():
        page_footer = f"\n{lines[-1].strip()}\n"
    
    return {
        "page": page_number,
        "text": text,
        "md": md_content,
        "images": page_images,
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
        "noTextContent": False,
        "pageHeaderMarkdown": page_header,
        "pageFooterMarkdown": page_footer,
        "confidence": 0.99
    }


def create_comprehensive_pages_structure(pages_data, filename):
    """Create comprehensive pages structure from extracted page data"""
    page_structures = []

    for page_data in pages_data:
        page_text = page_data.get("text", "")
        page_images = page_data.get("images", [])
        page_number = page_data.get("page_num", len(page_structures) + 1)
        page_tables = page_data.get("tables", [])

        pos_items = page_data.get("items_positional") or []
        if pos_items:
            items = list(pos_items)
            items = items + create_comprehensive_items_with_tables("", page_tables)
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
            "confidence": 1
        }

        page_structures.append(page_structure)

    return page_structures


def create_comprehensive_items_with_tables(text, tables):
    """Create comprehensive items array from text with proper formatting and tables.
    Reuse heading/numbered detection from create_comprehensive_items, then append tables.
    """
    text_items = create_comprehensive_items(text)

    if text_items:
        last = text_items[-1]
        y_position = last["bBox"]["y"] + last["bBox"]["h"] + 20
    else:
        y_position = 72.0

    items = list(text_items)

    for table_data in tables:
        if table_data and len(table_data) > 0:
            table_item = {
                "type": "table",
                "rows": table_data,
                "html": create_html_table_from_data(table_data),
                "md": create_table_markdown(table_data),
                "isPerfectTable": True,
                "csv": create_table_csv(table_data),
                "bBox": {
                    "x": 72.8,
                    "y": y_position,
                    "w": 449.8,
                    "h": 20 + (len(table_data) * 25)
                }
            }
            items.append(table_item)
            y_position += table_item["bBox"]["h"] + 20

    return items


def create_comprehensive_pages_structure_fallback(full_text, filename):
    """Fallback: Create comprehensive pages structure from text (for .doc files)"""
    pages_text = split_text_into_pages_advanced(full_text)
    
    page_structures = []
    for i, page_text in enumerate(pages_text, 1):
        page_structure = create_single_page_structure(page_text, i)
        page_structures.append(page_structure)
    
    return page_structures


async def extract_word_content(file_path, *_):
    """Main function to extract comprehensive content from Word document in exact JSON format"""
    start_time = time.time()
    filename = os.path.splitext(os.path.basename(file_path))[0]
    file_ext = os.path.splitext(file_path)[1].lower()
    
    print(f"Starting word extraction for: {file_path}")
    print(f"File extension: {file_ext}")
    
    try:
        img_root, img_summary_dir, img_vision_dir = await ensure_dirs()
        print(f"Directories ensured: {img_root}")
    except Exception as e:
        print(f"Error creating directories: {e}")
        raise
    
    try:
        if file_ext == '.docx':
            print(f"Processing DOCX file: {filename}")

            try:
                if os.name == 'nt':
                    possible_paths = [
                        r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
                        r"C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
                    ]
                    for p in possible_paths:
                        if os.path.exists(p):
                            pytesseract.pytesseract.tesseract_cmd = p
                            break
            except Exception:
                pass

            def convert_docx_to_pdf(docx_path: str) -> Optional[str]:
                try:
                    import win32com.client  # Requires Microsoft Word
                    word = win32com.client.Dispatch('Word.Application')
                    word.Visible = False
                    doc = word.Documents.Open(os.path.abspath(docx_path))
                    pdf_dir = os.path.join("output", "tmp_pdf")
                    os.makedirs(pdf_dir, exist_ok=True)
                    pdf_path = os.path.join(pdf_dir, f"{os.path.splitext(os.path.basename(docx_path))[0]}.pdf")
                    doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
                    doc.Close(False)
                    word.Quit()
                    return pdf_path
                except Exception as e:
                    print(f"DOCX->PDF conversion failed or Word not available: {e}")
                    return None

            def build_pages_from_pdf(pdf_path: str) -> List[dict]:
                import fitz, pdfplumber
                pages_collected: List[dict] = []
                with fitz.open(pdf_path) as pdf, pdfplumber.open(pdf_path) as plumber_pdf:
                    for i, (fz_page, pl_page) in enumerate(zip(pdf, plumber_pdf.pages), start=1):
                        page_text = (fz_page.get_text("text") or "").strip()

                        tables_rows: List[List[List[str]]] = []
                        try:
                            tables_raw = pl_page.extract_tables() or []
                            for t in tables_raw:
                                if t and any(any(cell for cell in row) for row in t):
                                    tables_rows.append([["" if cell is None else str(cell).strip() for cell in row] for row in t])
                        except Exception as te:
                            print(f"Table extraction error on page {i}: {te}")

                        page_images: List[dict] = []
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
                        except Exception as img_err:
                            print(f"Image block extraction error on page {i}: {img_err}")

                        try:
                            import fitz as _fitz
                            image_blocks_sorted = sorted(image_blocks, key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
                            for img_idx, blk in enumerate(image_blocks_sorted, start=1):
                                bbox = blk["bbox"]
                                rect = _fitz.Rect(bbox)
                                try:
                                    pix_clip = fz_page.get_pixmap(dpi=150, clip=rect)
                                    img_name = f"img_p{i}_{img_idx}.png"
                                    img_path = os.path.join(img_root, img_name)
                                    pix_clip.save(img_path)

                                    ocr_items = []
                                    try:
                                        from PIL import Image as PILImage
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
                                            conf_raw = data.get("conf", ["-1"]) [j]
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
                        except Exception as order_err:
                            print(f"Image ordering error on page {i}: {order_err}")

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
                        except Exception as re_err:
                            print(f"Page render error (screenshot) on page {i}: {re_err}")

                        pages_collected.append({
                            "text": page_text,
                            "tables": tables_rows,
                            "page_num": i,
                            "images": page_images,
                            "items_positional": sorted(page_text_items, key=lambda it: (it.get("bBox", {}).get("y", 0), it.get("bBox", {}).get("x", 0))),
                        })
                return pages_collected

            pdf_path = convert_docx_to_pdf(file_path)
            if pdf_path and os.path.exists(pdf_path):
                try:
                    pages_data = build_pages_from_pdf(pdf_path)
                    print(f"Extracted {len(pages_data)} pages via PDF pipeline")
                    pages = create_comprehensive_pages_structure(pages_data, filename)
                    print(f"Created comprehensive structure with {len(pages)} pages")
                except Exception as e:
                    print(f"PDF-based extraction failed: {e}. Falling back to DOCX paragraphs.")
                    doc = Document(file_path)
                    pages_data = extract_page_content_with_structure(doc, filename, img_root)
                    pages = create_comprehensive_pages_structure(pages_data, filename)
            else:
                print("PDF conversion not available, using DOCX paragraph-based heuristic.")
                doc = Document(file_path)
                pages_data = extract_page_content_with_structure(doc, filename, img_root)
                pages = create_comprehensive_pages_structure(pages_data, filename)
            
        else:
            print(f"Processing DOC file: {filename}")
            try:
                full_text = await extract_doc_content_comprehensive(file_path)
                if not full_text.strip():
                    raise Exception("No content extracted from .doc file")
                print(f"Extracted text content length: {len(full_text)}")
            except Exception as e:
                print(f"Error extracting .doc content: {e}")
                raise
            
            try:
                pages = create_comprehensive_pages_structure_fallback(full_text, filename)
                print(f"Created fallback structure with {len(pages)} pages")
            except Exception as e:
                print(f"Error creating fallback structure: {e}")
                raise
            
    except Exception as e:
        print(f"Primary extraction failed: {e}")
        print(f"Creating fallback content for: {file_path}")
        
        try:
            file_size = os.path.getsize(file_path)
            filename_base = os.path.basename(file_path)
        except Exception as size_error:
            print(f"Error getting file size: {size_error}")
            file_size = 0
            filename_base = "Unknown"
        
        try:
            with open(file_path, 'rb') as f:
                first_bytes = f.read(1024)
                readable_text = ""
                for encoding in ['utf-8', 'latin-1', 'cp1252']:
                    try:
                        decoded = first_bytes.decode(encoding, errors='ignore')
                        words = re.findall(r'[A-Za-z]{3,}', decoded)
                        if len(words) > 5:
                            readable_text = f"Document contains text including: {', '.join(words[:10])}"
                            break
                    except:
                        continue
        except Exception as read_error:
            print(f"Error reading file for fallback: {read_error}")
            readable_text = "Binary format document - content extraction failed"
        
        full_text = f"""Document: {filename_base}
File Size: {file_size:,} bytes
Format: {file_ext.upper()}

Processing Status: Content extraction encountered difficulties
Error: {str(e)}

{readable_text}

Note: This document requires specialized processing or format conversion.

Recommended Actions:
1. Verify file integrity
2. Convert to .docx format in Microsoft Word
3. Check for password protection
4. Try opening in compatible word processor

For best results, save as .docx format and re-upload."""

        try:
            pages = create_comprehensive_pages_structure_fallback(full_text, filename)
            print(f"Created fallback structure with {len(pages)} pages")
        except Exception as fallback_error:
            print(f"Error creating fallback structure: {fallback_error}")
            pages = [{
                "page": 1,
                "text": full_text,
                "md": full_text,
                "images": [],
                "charts": [],
                "items": [],
                "status": "ERROR",
                "originalOrientationAngle": 0,
                "links": [],
                "width": 595.303937007874,
                "height": 841.889763779528,
                "triggeredAutoMode": False,
                "parsingMode": "fallback",
                "structuredData": None,
                "noStructuredContent": True,
                "noTextContent": False,
                "pageHeaderMarkdown": "",
                "pageFooterMarkdown": "",
                "confidence": 0.1
            }]

    processing_time = time.time() - start_time
    print(f"Processing completed in {processing_time:.2f} seconds")
    
    result = {
        "pages": pages
    }
    
    output_path = os.path.join("output", f"{filename}.{file_ext.replace('.', '')}.json")
    try:
        os.makedirs("output", exist_ok=True)
        
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"Word JSON output saved to: {output_path}")
        print(f"Total pages extracted: {len(pages)}")
    except Exception as e:
        print(f"Warning: Could not save JSON output: {e}")
    
    try:
        await change_to_processed(file_path, 'Word')
        print(f"File moved to processed folder")
    except Exception as e:
        print(f"Warning: Could not move file to processed: {e}")
    
    print(f"Word extraction completed successfully for {filename}")
    return result
