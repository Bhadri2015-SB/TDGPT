import re
import uuid
from typing import List, Dict
from nltk.tokenize import sent_tokenize
from transformers import AutoTokenizer

# Load tokenizer for token counting (you can replace with any open-source tokenizer)
tokenizer = AutoTokenizer.from_pretrained("intfloat/e5-small-v2")


def is_heading(line: str) -> bool:
    """Detect if a line is a section heading using regex."""
    return bool(re.match(r"^\s*(\d+\.)+\s+[A-Z]", line.strip()))


def count_tokens(text: str) -> int:
    """Count the number of tokens using the tokenizer."""
    return len(tokenizer.tokenize(text))


def recursive_token_split(text: str, max_tokens: int = 200) -> List[str]:
    """Recursively split long sections into smaller chunks."""
    sentences = sent_tokenize(text)
    chunks = []
    current_chunk = ""
    current_tokens = 0

    for sent in sentences:
        token_count = count_tokens(sent)
        if current_tokens + token_count <= max_tokens:
            current_chunk += " " + sent
            current_tokens += token_count
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sent
            current_tokens = token_count

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def combine_page_content(page: dict) -> str:
    """Merge text, tables, and image descriptions."""
    text = page.get("text", "")
    tables = "\n".join(page.get("tables", [])) if isinstance(page.get("tables"), list) else page.get("tables", "")
    image_vision_desc = " ".join(img.get("description", "") for img in page.get("img_vision_files", []))
    image_ocr_desc = " ".join(img.get("description", "") for img in page.get("img_summary_files", []))
    return "\n".join([text, tables, image_vision_desc, image_ocr_desc]).strip()


def hybrid_chunk_pages(pages: List[Dict], max_tokens: int = 200) -> List[Dict]:
    """Hybrid chunking across pages and headings."""
    chunks = []
    chunk_id = 0

    for page in pages:
        page_number = page.get("page_number")
        combined_text = combine_page_content(page)
        lines = combined_text.splitlines()

        current_section = {"title": "", "body": ""}
        for line in lines:
            if is_heading(line):
                if current_section["body"]:
                    # Process previous section
                    section_text = current_section["body"].strip()
                    section_chunks = (
                        [section_text]
                        if count_tokens(section_text) <= max_tokens
                        else recursive_token_split(section_text, max_tokens)
                    )

                    for chunk in section_chunks:
                        chunks.append({
                            "chunk_id": chunk_id,
                            "section_title": current_section["title"],
                            "page_number": page_number,
                            "tokens": count_tokens(chunk),
                            "text": chunk.strip()
                        })
                        chunk_id += 1

                # Start new section
                current_section = {"title": line.strip(), "body": ""}
            else:
                current_section["body"] += " " + line.strip()

        # Final flush at end of page
        if current_section["body"]:
            section_text = current_section["body"].strip()
            section_chunks = (
                [section_text]
                if count_tokens(section_text) <= max_tokens
                else recursive_token_split(section_text, max_tokens)
            )
            for chunk in section_chunks:
                chunks.append({
                    "chunk_id": chunk_id,
                    "section_title": current_section["title"],
                    "page_number": page_number,
                    "tokens": count_tokens(chunk),
                    "text": chunk.strip()
                })
                chunk_id += 1

    return chunks
