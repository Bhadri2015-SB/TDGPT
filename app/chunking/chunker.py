# chunker.py

import json
from typing import List, Dict, Union
from transformers import AutoTokenizer
import os
import nltk
nltk.download('punkt')
import re
from nltk.tokenize import sent_tokenize



class Chunker:
    def __init__(self, json_path: str, tokenizer_model: str = "bert-base-uncased"):
        self.json_path = json_path
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_model)
        self.raw_data = self._load_data()
        self.pages = self.raw_data.get("pages", [])
        self.file_name = self.raw_data.get("metadata", {}).get("file_name", "unknown")

    def _load_data(self) -> Dict:
        if not os.path.exists(self.json_path):
            raise FileNotFoundError(f"File not found: {self.json_path}")
        with open(self.json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _combine_page_content(self, page: Dict) -> str:
        text = page.get("text", "")

        # Handle tables: list of dicts or strings
        tables_raw = page.get("tables", "")
        if isinstance(tables_raw, list):
            tables = "\n".join([json.dumps(t, ensure_ascii=False) if isinstance(t, dict) else str(t) for t in tables_raw])
        else:
            tables = str(tables_raw)

        # Handle vision and OCR image descriptions
        images_vision = page.get("img_vision_files", [])
        images_ocr = page.get("img_summary_files", [])
        image_vision_descriptions = " ".join(img.get("description", "") for img in images_vision)
        image_ocr_descriptions = " ".join(img.get("description", "") for img in images_ocr)

        content = "\n".join([text, tables, image_vision_descriptions, image_ocr_descriptions])
        return content.strip()


    def _token_count(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def chunk_by_fixed_tokens(self, max_tokens: int = 200) -> List[Dict]:
        chunks = []
        chunk_id = 0

        for page in self.pages:
            full_text = self._combine_page_content(page)
            tokens = self.tokenizer.encode(full_text, add_special_tokens=False)

            for i in range(0, len(tokens), max_tokens):
                chunk_tokens = tokens[i:i + max_tokens]
                chunk_text = self.tokenizer.decode(chunk_tokens)

                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page["page_number"],
                    "tokens": len(chunk_tokens),
                    "text": chunk_text.strip()
                })
                chunk_id += 1

        return chunks

    def chunk_by_sliding_window(self, max_tokens: int = 200, stride: int = 50) -> List[Dict]:
        chunks = []
        chunk_id = 0

        for page in self.pages:
            full_text = self._combine_page_content(page)
            tokens = self.tokenizer.encode(full_text, add_special_tokens=False)

            start = 0
            while start < len(tokens):
                end = min(start + max_tokens, len(tokens))
                chunk_tokens = tokens[start:end]
                chunk_text = self.tokenizer.decode(chunk_tokens)

                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page["page_number"],
                    "tokens": len(chunk_tokens),
                    "text": chunk_text.strip()
                })
                chunk_id += 1

                if end == len(tokens):
                    break
                start += stride

        return chunks
    
    def chunk_by_sentence_merge(self, max_tokens: int = 200) -> List[Dict]:
        chunks = []
        chunk_id = 0

        for page in self.pages:
            full_text = self._combine_page_content(page)
            sentences = sent_tokenize(full_text)
            current_chunk = ""
            current_tokens = 0

            for sent in sentences:
                sent_tokens = self._token_count(sent)

                # If sentence itself is longer than max, store as own chunk
                if sent_tokens > max_tokens:
                    if current_chunk:
                        chunks.append({
                            "chunk_id": chunk_id,
                            "page_number": page["page_number"],
                            "tokens": current_tokens,
                            "text": current_chunk.strip()
                        })
                        chunk_id += 1
                    chunks.append({
                        "chunk_id": chunk_id,
                        "page_number": page["page_number"],
                        "tokens": sent_tokens,
                        "text": sent.strip()
                    })
                    chunk_id += 1
                    current_chunk = ""
                    current_tokens = 0
                    continue

                # If current chunk + sentence fits, add it
                if current_tokens + sent_tokens <= max_tokens:
                    current_chunk += " " + sent
                    current_tokens += sent_tokens
                else:
                    chunks.append({
                        "chunk_id": chunk_id,
                        "page_number": page["page_number"],
                        "tokens": current_tokens,
                        "text": current_chunk.strip()
                    })
                    chunk_id += 1
                    current_chunk = sent
                    current_tokens = sent_tokens

            if current_chunk:
                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page["page_number"],
                    "tokens": current_tokens,
                    "text": current_chunk.strip()
                })
                chunk_id += 1

        return chunks

    def chunk_by_paragraph_split(self, max_tokens: int = 200) -> List[Dict]:
        chunks = []
        chunk_id = 0

        for page in self.pages:
            full_text = self._combine_page_content(page)
            paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            current_chunk = ""
            current_tokens = 0

            for para in paragraphs:
                para_tokens = self._token_count(para)

                if para_tokens > max_tokens:
                    if current_chunk:
                        chunks.append({
                            "chunk_id": chunk_id,
                            "page_number": page["page_number"],
                            "tokens": current_tokens,
                            "text": current_chunk.strip()
                        })
                        chunk_id += 1
                    chunks.append({
                        "chunk_id": chunk_id,
                        "page_number": page["page_number"],
                        "tokens": para_tokens,
                        "text": para.strip()
                    })
                    chunk_id += 1
                    current_chunk = ""
                    current_tokens = 0
                    continue

                if current_tokens + para_tokens <= max_tokens:
                    current_chunk += " " + para
                    current_tokens += para_tokens
                else:
                    chunks.append({
                        "chunk_id": chunk_id,
                        "page_number": page["page_number"],
                        "tokens": current_tokens,
                        "text": current_chunk.strip()
                    })
                    chunk_id += 1
                    current_chunk = para
                    current_tokens = para_tokens

            if current_chunk:
                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page["page_number"],
                    "tokens": current_tokens,
                    "text": current_chunk.strip()
                })
                chunk_id += 1

        return chunks

    def log_chunking_result(self, strategy: str, chunks: List[Dict], output_path: str):
        token_lengths = [chunk["tokens"] for chunk in chunks]
        result = {
            "strategy": strategy,
            "file_name": self.file_name,
            "total_chunks": len(chunks),
            "avg_tokens_per_chunk": round(sum(token_lengths) / len(token_lengths), 2) if chunks else 0,
            "min_tokens": min(token_lengths) if chunks else 0,
            "max_tokens": max(token_lengths) if chunks else 0,
            "sample_chunks": chunks[:3]
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    def chunk_by_recursive_split(self, max_tokens: int = 200) -> List[Dict]:
        chunks = []
        chunk_id = 0

        for page in self.pages:
            text = self._combine_page_content(page)
            units = self._recursive_split(text, max_tokens)

            for unit in units:
                chunks.append({
                    "chunk_id": chunk_id,
                    "page_number": page["page_number"],
                    "tokens": self._token_count(unit),
                    "text": unit.strip()
                })
                chunk_id += 1

        return chunks

    def _recursive_split(self, text: str, max_tokens: int) -> List[str]:
        if self._token_count(text) <= max_tokens:
            return [text]

        # Step 1: Paragraphs
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        paragraph_chunks = self._recursive_split_units(paragraphs, max_tokens)
        if paragraph_chunks:
            return paragraph_chunks

        # Step 2: Sentences
        sentences = sent_tokenize(text)
        sentence_chunks = self._recursive_split_units(sentences, max_tokens)
        if sentence_chunks:
            return sentence_chunks

        # Step 3: Words fallback
        words = text.split()
        return self._merge_by_token_limit(words, max_tokens)

    def _recursive_split_units(self, units: List[str], max_tokens: int) -> List[str]:
        chunks = []
        current_chunk = ""
        current_tokens = 0

        for unit in units:
            unit_tokens = self._token_count(unit)
            if unit_tokens > max_tokens:
                return []  # fallback required

            if current_tokens + unit_tokens <= max_tokens:
                current_chunk += " " + unit
                current_tokens += unit_tokens
            else:
                chunks.append(current_chunk.strip())
                current_chunk = unit
                current_tokens = unit_tokens

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _merge_by_token_limit(self, words: List[str], max_tokens: int) -> List[str]:
        chunks = []
        current_chunk = []
        current_tokens = 0

        for word in words:
            word_tokens = self._token_count(word)
            if current_tokens + word_tokens > max_tokens:
                chunks.append(" ".join(current_chunk).strip())
                current_chunk = [word]
                current_tokens = word_tokens
            else:
                current_chunk.append(word)
                current_tokens += word_tokens

        if current_chunk:
            chunks.append(" ".join(current_chunk).strip())

        return chunks

    def chunk_by_hybrid(self, max_tokens: int = 200) -> List[Dict]:
        # from app.chunking.hybrid_chunking import hybrid_chunk_pages  # Adjust import if needed
        return hybrid_chunk_pages(self.pages, max_tokens=max_tokens)




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
    # tables = "\n".join(page.get("tables", [])) if isinstance(page.get("tables"), list) else page.get("tables", "")

    tables_raw = page.get("tables", "")
    if isinstance(tables_raw, list):
        tables = "\n".join([json.dumps(t, ensure_ascii=False) if isinstance(t, dict) else str(t) for t in tables_raw])
    else:
        tables = str(tables_raw)
        
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
