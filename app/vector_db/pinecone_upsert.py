
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import dotenv
import requests
from pinecone import Pinecone, ServerlessSpec

from llama_index import VectorStoreIndex, ServiceContext
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.ingestion import IngestionPipeline
from llama_index.node_parser import SemanticSplitterNodeParser
from llama_index.readers.schema import Document
from llama_index.retrievers import VectorIndexRetriever
from llama_index.vector_stores import PineconeVectorStore

from app.core import config
from app.utils.file_handler import get_file_category  


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Admin



dotenv.load_dotenv()





PAGE_LINK_IMAGES_ONLY = True


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _derive_image_prefix(file_name: str) -> str:
    """Derive a stable short prefix for image files from a JSON file name like 'qq.docx.json' -> 'qq'.
    If no clear double-suffix, fall back to stem without '.json'.
    """
    try:
        base = file_name
        if base.lower().endswith('.json'):
            base = base[:-5]
        for suf in ('.docx', '.doc', '.pdf', '.pptx', '.ppt', '.md'):
            if base.lower().endswith(suf):
                base = base[: -len(suf)]
                break
        base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip('_') or 'file'
        return base
    except Exception:
        return 'file'


def _ensure_images_namespaced(json_path: Path) -> Dict[str, Any]:
    """Rename this document's images to include a per-file prefix and update JSON in place.
    - inline images: 'img_p{page}_{i}.png' -> '{prefix}_img_p{page}_{i}.png'
    - screenshots: 'page_{page}.jpg' -> '{prefix}_page_{page}.jpg'
    Idempotent: skips if already prefixed or target exists.
    Returns a summary dict with counts.
    """
    data = _safe_json_load(json_path) or {}
    fname = data.get("metadata", {}).get("file_name", json_path.name)
    prefix = _derive_image_prefix(fname)
    images_dir = json_path.parent / "images"
    changed = 0
    skipped = 0
    missing = 0
    pages = data.get("pages") or []
    for p in pages:
        pnum = p.get("page") or p.get("page_number")
        try:
            pnum = int(pnum or -1)
        except Exception:
            pnum = -1
        for im in (p.get("images") or []):
            name = im.get("name") or im.get("filename") or ""
            if not name:
                continue
            # Already namespaced with this prefix
            if name.startswith(prefix + "_"):
                continue
            # Compute target name
            if (im.get("type") or im.get("img_type")) == "full_page_screenshot":
                m = re.search(r"page_([0-9]+)\.(jpg|jpeg|png)$", name, flags=re.IGNORECASE)
                if m and pnum > 0:
                    new_name = f"{prefix}_page_{pnum}.{m.group(2).lower()}"
                else:
                    new_name = f"{prefix}_{name}"
            else:
                m2 = re.search(r"img_p([0-9]+)_([0-9]+)\.(png|jpg|jpeg)$", name, flags=re.IGNORECASE)
                if m2 and pnum > 0:
                    ext = m2.group(3).lower()
                    idx = int(m2.group(2))
                    new_name = f"{prefix}_img_p{pnum}_{idx}.{ext}"
                else:
                    new_name = f"{prefix}_{name}"
            src = images_dir / name
            dst = images_dir / new_name
            try:
                if dst.exists():
                    skipped += 1
                elif src.exists():
                    src.rename(dst)
                    changed += 1
                else:
                    missing += 1
                if im.get("name"):
                    im["name"] = new_name
                if im.get("filename"):
                    im["filename"] = new_name
            except Exception:
                skipped += 1
                continue
    # Write back JSON
    try:
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {"file": fname, "prefix": prefix, "renamed": changed, "skipped": skipped, "missing": missing}


async def get_available_indexes() -> List[str]:
    """List all Pinecone index names."""
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    return pc.list_indexes().names()


def _clean_name(name: str) -> str:
    """
    Pinecone index safe: keep alphanumerics only (lowercase).
    We keep digits to avoid collisions like AA1 vs AA2.
    No special case mapping - consistent cleaning for all names.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", name).lower()
    return cleaned or "defaultindex"



_EMBED_MODEL: Optional[HuggingFaceEmbedding] = None


def _get_embed_model(
    model_name: str = "BAAI/bge-small-en-v1.5",
    device: str = "cpu",
    embed_batch_size: int = 8,
) -> HuggingFaceEmbedding:
    """Return (and cache) embedding model instance."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = HuggingFaceEmbedding(
            model_name=model_name,
            device=device,
            embed_batch_size=embed_batch_size,
        )
    return _EMBED_MODEL




async def _combine_page_content(page: Dict) -> str:
    text = page.get("text", "")

    tables_raw = page.get("tables", "")
    if isinstance(tables_raw, list):
        tables = "\n".join(
            [
                json.dumps(t, ensure_ascii=False) if isinstance(t, dict) else str(t)
                for t in tables_raw
            ]
        )
    else:
        tables = str(tables_raw)

   
    images_vision = page.get("img_vision_files", [])
    images_ocr = page.get("img_summary_files", [])
    vision_text = " ".join(img.get("description", "") for img in images_vision)
   
    ocr_text = " ".join(
        (img.get("ocr_text") or img.get("description") or "") for img in images_ocr
    )

    return "\n".join([text, tables, vision_text, ocr_text]).strip()


async def _load_pdf_like_documents(json_path: Path) -> List[Document]:
    """Generic loader used for PDF, Word, etc. that follow 'pages' structure."""
    data = _safe_json_load(json_path) or {}
    docs: List[Document] = []
    pages = data.get("pages", [])
    fname = data.get("metadata", {}).get("file_name", json_path.name)
    for page in pages:
        enriched = await _combine_page_content(page)
       
        pnum_raw = page.get("page_number") if page.get("page_number") is not None else page.get("page")
        try:
            pnum = int(pnum_raw) if pnum_raw is not None else None
        except Exception:
            pnum = None

        meta = {"file_name": fname}
        if pnum is not None:
            meta["page_number"] = pnum

        docs.append(
            Document(
                text=enriched,
                metadata=meta,
            )
        )
    return docs


async def _index_images_from_word_document(json_path: Path, admin_name: str) -> Dict[str, Any]:
    """Index images from Word document JSON structure into Pinecone using simple CLIP embeddings."""
    from app.vector_db.upsert_image import embed_image
    import os
    
    data = _safe_json_load(json_path) or {}
    fname = data.get("metadata", {}).get("file_name", json_path.name)
    pages = data.get("pages", [])
    
    index_name_clean = _clean_name(admin_name)
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    
    
    if index_name_clean not in pc.list_indexes().names():
        pc.create_index(
            name=index_name_clean,
            dimension=384,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    
    idx = pc.Index(index_name_clean)
    vectors = []
    processed_images = 0
    errors = []
    
    base_dir = json_path.parent  
    
    def _compose_caption(img: Dict) -> Dict[str, str]:
        """Compose caption and ocr_text from image info (anchors + OCR)."""
        anchors = img.get("anchors") or {}
        heading = (anchors.get("heading") or {}).get("text") if isinstance(anchors, dict) else None
        above = (anchors.get("above_text") or {}).get("text") if isinstance(anchors, dict) else None
        below = (anchors.get("below_text") or {}).get("text") if isinstance(anchors, dict) else None
       
        ocr_items = img.get("ocr") or []
        try:
            ocr_text = " ".join([o.get("text", "") for o in ocr_items if (o.get("text") or "").strip()])
        except Exception:
            ocr_text = ""
       
        parts = []
        if heading and heading.strip():
            parts.append(heading.strip())
        if below and below.strip():
            parts.append(below.strip())
        elif above and above.strip():
            parts.append(above.strip())
        cap = " - ".join(parts)
        if not cap and ocr_text:
            cap = ocr_text[:120]
        
        if cap:
            cap = cap[:220]
        if ocr_text:
            ocr_text = ocr_text[:500]
        return {"caption": cap or "", "ocr_text": ocr_text or ""}

    for page in pages:
      
        raw_pnum = page.get("page_number") if page.get("page_number") is not None else page.get("page")
        try:
            page_num = int(raw_pnum) if raw_pnum is not None else None
        except Exception:
            page_num = None

        
        for img_info in (page.get("images", []) or []):
            
            if (img_info.get("type") or img_info.get("img_type")) in {"full_page_screenshot", "screenshot"}:
                continue

            img_filename = img_info.get("filename") or img_info.get("name", "")
            if not img_filename:
                continue

            
            img_path = base_dir / "images" / img_filename
            if not img_path.exists():
                errors.append(f"Image not found: {img_path}")
                continue

            try:
                
                vec = await embed_image(img_path, model_type="clip")

                cap = _compose_caption(img_info)
                metadata = {
                    "type": "image",
                    "img_type": "inline",  
                    "source_file": fname,
                    "filename": img_filename,
                    **({"page_number": page_num} if page_num is not None else {}),
                    "url": f"/output/images/{img_filename}",
                    "full_path": str(img_path),
                    "file_name": fname,  
                    "admin_name": admin_name,
                    **({"caption": cap.get("caption")} if cap.get("caption") else {}),
                    **({"ocr_text": cap.get("ocr_text")} if cap.get("ocr_text") else {}),
                }

                vectors.append({
                    "id": f"img::{fname}::{img_filename}",
                    "values": vec.tolist(),
                    "metadata": metadata,
                })
                processed_images += 1

            except Exception as e:
                errors.append(f"Error processing {img_filename}: {str(e)}")
                continue
    
  
    result = {"processed_images": 0, "errors": errors}
    if vectors:
        try:
            idx.upsert(vectors=vectors)
            result["processed_images"] = processed_images
        except Exception as e:
            result["errors"].append(f"Upsert failed: {str(e)}")
    
    return result


async def _flattened_json_to_documents(json_path: Path) -> List[Document]:
    data = _safe_json_load(json_path) or {}
    lines = [f"{k}: {v}" for k, v in data.items()]
    fname = json_path.name.removesuffix(".json")
    return [Document(text="\n".join(lines), metadata={"file_name": fname})]


async def _sqlite_to_documents(json_path: Path) -> List[Document]:
    data = _safe_json_load(json_path) or {}
    docs: List[Document] = []
    for table_name, table_info in data.items():
        columns = table_info.get("columns", [])
        rows = table_info.get("data", [])
        lines = [
            f"Table: {table_name}",
            f"Columns: {', '.join(columns)}",
            "Rows:",
        ]
        for row in rows:
            row_str = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"  - {row_str}")
        docs.append(Document(text="\n".join(lines), metadata={"table_name": table_name}))
    return docs


async def _excel_to_documents(json_path: Path) -> List[Document]:
    data = _safe_json_load(json_path) or {}
    fname = data.get("metadata", {}).get("file_name", "unknown_file")
    by_sheet: Dict[str, List[str]] = {}
    for item in data.get("content", []):
        sheet = item.get("sheet", "Sheet1")
        row_num = item.get("row_number")
        row_data = item.get("row_data", {})
        row_text = f"Row {row_num}: " + ", ".join(f"{k}={v}" for k, v in row_data.items())
        by_sheet.setdefault(sheet, []).append(row_text)

    docs: List[Document] = []
    for sheet, rows in by_sheet.items():
        text = f"Sheet: {sheet}\n" + "\n".join(rows)
        docs.append(Document(text=text, metadata={"file_name": fname}))
    return docs


async def _markdown_to_documents(json_path: Path) -> List[Document]:
    data = _safe_json_load(json_path) or {}
    meta = data.get("metadata", {})
    blocks = data.get("content", [])

    docs: List[Document] = []
    cur_text = ""
    cur_heading: Optional[str] = None

    def _flush():
        nonlocal cur_text, cur_heading, docs
        if cur_heading or cur_text.strip():
            docs.append(
                Document(
                    text=cur_text.strip(),
                    metadata={"heading": cur_heading, "file_name": meta.get("file_name", "unknown")},
                )
            )
        cur_text = ""

    for block in blocks:
        btype = block.get("type")
        if btype == "heading":
            _flush()
            cur_heading = block.get("text", "Untitled Section")
        elif btype == "paragraph":
            cur_text += block.get("text", "") + "\n"
        elif btype == "list":
            for item in block.get("items", []):
                cur_text += f"- {item}\n"
        elif btype == "code_block":
            lang = block.get("language", "")
            code = block.get("code", "")
            cur_text += f"```{lang}\n{code}\n```\n"

    _flush()
    return docs


async def _ppt_to_documents(json_path: Path) -> List[Document]:
    data = _safe_json_load(json_path) or {}
    fname = data.get("metadata", {}).get("file_name", json_path.name)
    slides = data.get("slides", [])
    docs: List[Document] = []
    for slide in slides:
        s_num = slide.get("slide_number", -1)
        text_blocks = slide.get("text_blocks", [])
        ocr_texts = slide.get("img_summary_texts", [])
        vision_desc = slide.get("img_vision_descriptions", [])
        parts = []
        if text_blocks:
            parts.append("Text Blocks:\n" + "\n".join(f"- {t}" for t in text_blocks))
        if ocr_texts:
            parts.append("Image OCR Texts:\n" + "\n".join(f"- {t}" for t in ocr_texts))
        if vision_desc:
            parts.append("Image Descriptions:\n" + "\n".join(f"- {d}" for d in vision_desc))
        text = f"Slide {s_num}\n" + "\n\n".join(parts)
        docs.append(Document(text=text, metadata={"file_name": fname, "slide_number": s_num}))
    return docs




async def _detect_category_from_extracted_file(path: Path) -> str:
    """Infer the original file category from extracted JSON."""
    data = _safe_json_load(path) or {}
    meta = data.get("metadata", {})
    ft = (meta.get("file_type") or meta.get("filetype") or "").strip()
    if ft:
        ft_up = ft.upper()
        if ft_up in {"PDF", "WORD", "MD", "PPT", "EXCEL", "JSON", "SQLITE"}:
            return ft_up
        if ft_up in {"CSV"}:
            return "EXCEL"

   
    stem_parts = path.name.split(".")
    if len(stem_parts) >= 3:
        ext_guess = stem_parts[-2].lower()
        cat = await get_file_category("." + ext_guess)
        if cat:
            return cat.upper()


    if path.suffix.lower() == ".json":
        return "JSON"
    return "UNKNOWN"



async def upsert_documents_to_pinecone(
    documents_path: str,
    admin_id: str,
    admin_name: str,
) -> Dict[str, Any]:
    """
    Embed & upsert extracted document content into a Pinecone index derived
    from `admin_name`. Return status dict for DB updates.
    """
    path = Path(documents_path)
    file_base = path.name.removesuffix(".json")

    category = await _detect_category_from_extracted_file(path)

    try:
        # Ensure per-file image namespacing to avoid cross-file collisions
        try:
            _ensure_images_namespaced(path)
        except Exception:
            pass
        if category in {"SQLITE", "SQL_SCRIPT"}:
            docs = await _sqlite_to_documents(path)
        elif category in {"EXCEL"}:  # Excel/CSV
            docs = await _excel_to_documents(path)
        elif category == "JSON":
            docs = await _flattened_json_to_documents(path)
        elif category == "MD":
            docs = await _markdown_to_documents(path)
        elif category == "PPT":
            docs = await _ppt_to_documents(path)
        else:
            docs = await _load_pdf_like_documents(path)
    except Exception as e:
        return {
            "admin_id": admin_id,
            "file_name": file_base,
            "status": "Embedding failed",
            "message": f"Doc build error: {e}",
        }

    index_name_clean = _clean_name(admin_name)

    try:
        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        if index_name_clean not in pc.list_indexes().names():
            pc.create_index(
                name=index_name_clean,
                dimension=384,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

        pinecone_index = pc.Index(index_name_clean)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)

        embed_model = _get_embed_model()

        pipeline = IngestionPipeline(
            transformations=[
                SemanticSplitterNodeParser(
                    buffer_size=1,
                    breakpoint_percentile_threshold=95,
                    embed_model=embed_model,
                ),
                embed_model,
            ],
            vector_store=vector_store,
        )

        await asyncio.to_thread(pipeline.run, documents=docs, show_progress=False)

       
        image_result = {"processed_images": 0, "errors": []}
        if category not in {"SQLITE", "SQL_SCRIPT", "EXCEL", "JSON", "MD", "PPT"}:
            try:
                image_result = await _index_images_from_word_document(path, admin_name)
            except Exception as e:
                image_result["errors"].append(f"Image indexing failed: {str(e)}")

        message = "File successfully processed and embedded."
        if image_result["processed_images"] > 0:
            message += f" Also indexed {image_result['processed_images']} images."
        if image_result["errors"]:
            message += f" Image errors: {len(image_result['errors'])} issues."

        return {
            "admin_id": admin_id,
            "file_name": file_base,
            "status": "Processed",
            "message": message,
        }

    except Exception as e:
        print(f"[Upsert-ERROR] {path}: {e}")
        return {
            "admin_id": admin_id,
            "file_name": file_base,
            "status": "Embedding failed",
            "message": f"Error during upsert: {e}",
        }


async def delete_document_from_pinecone(file_name: str, admin_name: str) -> Dict[str, Any]:
    """Delete all vectors (text + images) related to a given file from the admin's Pinecone index."""
    try:
        index_name_clean = _clean_name(admin_name)
        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        if index_name_clean not in pc.list_indexes().names():
            return {"status": "not_found", "message": f"Index '{index_name_clean}' does not exist."}

        idx = pc.Index(index_name_clean)

       
        delete_filter = {
            "$or": [
                {"file_name": {"$eq": file_name}},
                {"source_file": {"$eq": file_name}},
            ]
        }

        try:
            idx.delete(filter=delete_filter)
        except Exception as e:
            return {"status": "error", "message": f"Delete failed: {e}"}

        return {"status": "deleted", "file_name": file_name, "index": index_name_clean}
    except Exception as e:
        return {"status": "error", "message": str(e)}


  




async def _llm_call(retrieved_text: str, query: str) -> Any:
    """
    Call LLM only if we have non-empty context text.
    If no context: return strict fallback (no hallucinations).
    """
    if not retrieved_text.strip():
        return "The answer is not available in the provided context."

    groq_api_key = config.GROQ_API_KEY
   
    model_sequence = [getattr(config, "GROQ_MODEL", "llama-3.1-8b-instant")]
    for fb in getattr(config, "GROQ_MODEL_FALLBACKS", []):
        if fb not in model_sequence:
            model_sequence.append(fb)

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "You are an expert domain assistant that provides helpful answers based on the available context.\n"
        "- Use the retrieved context as your primary source of information.\n"
        "- If the context contains relevant information (even if partially unclear), provide the best answer you can.\n"
        "- Only say 'The answer is not available in the provided context.' if the context is completely unrelated to the query.\n"
        "- Preserve technical formatting and provide clear, structured responses.\n"
    )

    try:
        last_error = None
        for mdl in model_sequence:
            payload = {
                "model": mdl,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context:\n{retrieved_text}\n\nUser Query: {query}"},
                ],
                "temperature": 0.3,
                "max_tokens": 512,
            }
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            if resp.status_code != 200:
                last_error = f"Groq API {resp.status_code}: {resp.text}"
                try:
                    msg = resp.json()
                except Exception:
                    msg = {"error": resp.text}
                msg_str = str(msg)
                if "model_decommissioned" in msg_str or "decommissioned" in msg_str or resp.status_code in (400, 404):
                    continue
                break
            data = resp.json()
            try:
                content = data["choices"][0]["message"].get("content")
                if content:
                    return content
            except Exception:
                last_error = "Unexpected Groq response format."
                continue
        return {"error": last_error or "All Groq models failed"}
    except Exception as e:
        return {"error": str(e)}




def _is_visual_query(query: str) -> bool:
    """
    Visual/text mode detection previously relied on keyword lists. Per requirements,
    remove all hardcoded keywords. Default to text mode (False) and let generic
    same-page image selection logic handle images when needed.
    """
    return False


async def retrival(
    query: str,
    admin_name: Optional[str] = None,
    *,
    index_name: Optional[str] = None,
    top_k: int = 5,
) -> Any:
    """
    Enhanced retrieval that automatically handles both text and image search.
    
    - For visual queries: prioritizes image results + relevant text context
    - For text queries: prioritizes text with related images as context
    - Returns unified response with both text answer and image URLs
    """
    try:
        raw_name = index_name or admin_name or "defaultindex"
        index_name_clean = _clean_name(raw_name)

        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        available_indexes = pc.list_indexes().names()
        if index_name_clean not in available_indexes:
            return {
                "error": f"No Pinecone index named '{index_name_clean}' for admin '{admin_name}'.\nAvailable indexes: {available_indexes}"
            }

    
        is_visual = _is_visual_query(query)
        
      
        retrieved_text = ""
        images = []
        
       
        pinecone_index = pc.Index(index_name_clean)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)
        embed_model = _get_embed_model()
        service_context = ServiceContext.from_defaults(llm=None, embed_model=embed_model)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
        
  
        retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)
        nodes = await asyncio.to_thread(retriever.retrieve, query)
        
       
        text_nodes = [n for n in nodes if n.node.metadata.get("type") != "image"]
        retrieved_text = "\n\n".join([n.node.text for n in text_nodes if hasattr(n.node, 'text')])
        
        
        relevant_files = set()
        file_scores: Dict[str, float] = {}
        page_scores: Dict[tuple, float] = {}  
        best_node_score = float("-inf")
        best_node_file: Optional[str] = None
        best_node_page: Optional[int] = None
        for n in text_nodes:
            fname = n.node.metadata.get("file_name", "")
            pnum = n.node.metadata.get("page_number")
            if fname:
                relevant_files.add(fname)
                score = float(getattr(n, "score", 0) or 0)
               
                if score > best_node_score:
                    best_node_score = score
                    best_node_file = fname
                    try:
                        best_node_page = int(pnum) if pnum is not None else None
                    except Exception:
                        best_node_page = None
               
                if fname not in file_scores or score > file_scores[fname]:
                    file_scores[fname] = score
                if pnum is not None:
                    key = (fname, int(pnum))
                    if key not in page_scores or score > page_scores[key]:
                        page_scores[key] = score
        
        primary_file = None
        secondary_files = []
        if file_scores:
            sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
            primary_file = sorted_files[0][0]
            primary_score = sorted_files[0][1]
            
            for fname, score in sorted_files[1:]:
                if abs(primary_score - score) < 0.015:
                    secondary_files.append(fname)

        primary_pages: List[int] = []
        if primary_file:
            candidates = [(p, s) for (f, p), s in page_scores.items() if f == primary_file]
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                top_page, top_score = candidates[0]
                primary_pages = [top_page]
                for p, s in candidates[1:]:
                    if abs(top_score - s) < 0.01:
                        primary_pages.append(p)

        # JSON-based page inference: pick the page whose on-page text best matches the query
        # This avoids vector drift picking a wrong page while keeping same-page guarantees.
        try:
            def _json_best_page_for_query(file_name: str, q: str) -> Optional[int]:
                import re as _re5
                from pathlib import Path as _P
                q = (q or "").strip()
                if not q:
                    return None
                def _tokens2(s: str):
                    return _re5.findall(r"[a-z0-9]+", (s or "").lower())
                def _overlap2(qt, text: str) -> int:
                    st = set(_tokens2(text))
                    return sum(1 for t in qt if t in st)
                def _norm_ns(s: str) -> str:
                    return _re5.sub(r"\s+", "", (s or "").lower())
                qt = _tokens2(q)
                q_ns = _norm_ns(q)
                json_candidates = [
                    config.OUTPUT_DIRECTORY / file_name,
                    (_P(config.BASE_DIR).parent / "output" / file_name),
                ]
                # First pass: exact normalized phrase containment in HEADINGS wins outright
                exact_matches: List[int] = []
                # Second pass: token + phrase-weight scoring
                best = None
                best_sc = -1.0
                for jp in json_candidates:
                    if not jp.exists():
                        continue
                    data = _safe_json_load(jp) or {}
                    for p in (data.get("pages") or []):
                        try:
                            pn = int(p.get("page") or p.get("page_number") or -1)
                        except Exception:
                            pn = -1
                        if pn <= 0:
                            continue
                        # Build a bag from page-level text/md, items, and image anchors/OCR
                        items2 = p.get("items") or []
                        page_text_chunks = []
                        headings: List[str] = []
                        table_cells = 0
                        # Page-level text and md (some extractors keep step lines here)
                        try:
                            if p.get("text"):
                                page_text_chunks.append(p.get("text") or "")
                        except Exception:
                            pass
                        try:
                            if p.get("md"):
                                page_text_chunks.append(p.get("md") or "")
                        except Exception:
                            pass
                        for it in items2:
                            t = (it.get("type") or it.get("item_type") or "").lower()
                            if t in ("text", "heading"):
                                val_txt = (it.get("value") or it.get("md") or "")
                                page_text_chunks.append(val_txt)
                                if t == "heading":
                                    headings.append(val_txt)
                            elif t == "table":
                                rows = it.get("rows") or []
                                try:
                                    for r in rows:
                                        table_cells += len(r)
                                except Exception:
                                    pass
                        # Include OCR/anchors from images on the page
                        for im in (p.get("images") or []):
                            a = im.get("anchors") or {}
                            page_text_chunks.append(((a.get("heading") or {}).get("text") or ""))
                            page_text_chunks.append(((a.get("above_text") or {}).get("text") or ""))
                            page_text_chunks.append(((a.get("below_text") or {}).get("text") or ""))
                            for e in (im.get("ocr") or []):
                                page_text_chunks.append(e.get("text") or "")
                        bag = " \n ".join(page_text_chunks)
                        # Exact phrase pass (in headings only)
                        try:
                            if q_ns and any(q_ns in _norm_ns(hv) for hv in headings):
                                exact_matches.append(pn)
                                continue
                        except Exception:
                            pass
                        # Score: token overlap + phrase containment + heading-aware + table density - TOC-like penalty
                        tok_sc = _overlap2(qt, bag)
                        ns_sc = 5.0 if (q_ns and q_ns in _norm_ns(bag) and len(q_ns) >= 10) else 0.0
                        head_bonus = 0.0
                        try:
                            for hv in headings:
                                hns = _norm_ns(hv)
                                if hns and (hns == q_ns or q_ns in hns or hns in q_ns):
                                    head_bonus = max(head_bonus, 10.0)
                                else:
                                    htok = set(_tokens2(hv))
                                    inter = len([t for t in qt if t in htok])
                                    if htok and inter / max(1, len(htok)) >= 0.6:
                                        head_bonus = max(head_bonus, 6.0)
                        except Exception:
                            pass
                        # small boost if layout suggests procedural text present
                        step_boost = 1.0 if (tok_sc >= 1 and len(page_text_chunks) >= 2) else 0.0
                        # table density bonus (helps large tables like troubleshooting lists)
                        table_bonus = 0.0
                        if tok_sc >= 1 or head_bonus > 0 or ns_sc > 0:
                            # each 30 cells ~ +1 up to +8
                            table_bonus = min(8.0, (float(table_cells) / 30.0))
                        # TOC-like penalty: many dot leaders or trailing page numbers across lines
                        toc_pen = 0.0
                        try:
                            lines = [ln.strip() for ln in (bag.splitlines() if isinstance(bag, str) else []) if ln.strip()]
                            if lines:
                                dotleaders = sum(1 for ln in lines if _re5.search(r"\.{3,}", ln))
                                trailing_nums = sum(1 for ln in lines if _re5.search(r"\b\d{1,3}\s*$", ln))
                                ratio = (dotleaders + trailing_nums) / max(1, len(lines))
                                # apply penalty only when no strong heading match
                                if head_bonus < 8.0 and ratio >= 0.3:
                                    toc_pen = min(6.0, 12.0 * ratio)
                        except Exception:
                            pass
                        sc = tok_sc + ns_sc + head_bonus + step_boost + table_bonus - toc_pen
                        try:
                            # Debug: log salient features for pages with heading or TOC signals
                            if head_bonus > 0 or toc_pen > 0:
                                print(f"[JSON-Page-Inference] file={file_name} page={pn} tok_sc={tok_sc} head_bonus={head_bonus} table_cells={table_cells} toc_pen={toc_pen} score={sc}")
                        except Exception:
                            pass
                        if sc > best_sc:
                            best_sc = sc
                            best = pn
                if exact_matches:
                    # If multiple, prefer the earliest page number
                    sel = sorted(set(exact_matches))[0]
                    try:
                        print(f"[JSON-Page-Inference] exact heading match -> page {sel}")
                    except Exception:
                        pass
                    return sel
                try:
                    print(f"[JSON-Page-Inference] best_page={best} best_sc={best_sc}")
                except Exception:
                    pass
                return best if best_sc > 0 else None

            # If JSON scoring finds a strong page on the primary file, prefer it over vector top
            json_best_page = _json_best_page_for_query(primary_file, query) if primary_file else None
            if json_best_page is not None:
                best_node_page = json_best_page
                primary_pages = [json_best_page]
                try:
                    print(f"[Retrieval] JSON page inference selected page {json_best_page} for {primary_file}")
                except Exception:
                    pass
        except Exception:
            pass

    
        if not PAGE_LINK_IMAGES_ONLY:
            try:
                from app.vector_db.upsert_image import search_images
                image_top_k = 8 if is_visual else 5
                clip_images = await search_images(query, index_name_clean, top_k=image_top_k, model_type="clip")
                filtered_clip_images = []
                for img in clip_images:
                    img_source_file = img.get("source_file") or ""
                    if not img_source_file:
                        continue
                    base_file = img_source_file.split("_page")[0] if "_page" in img_source_file else img_source_file.split(".")[0]
                    img_page_num = img.get("page_number")
                    if is_visual:
                        is_relevant = (primary_file and (base_file in primary_file or primary_file in base_file)) or \
                                      any(base_file in sf or sf in base_file for sf in secondary_files)
                        page_priority = 2 if (img_page_num is not None and img_page_num in primary_pages) else 1
                        if is_relevant or not relevant_files:
                            filtered_clip_images.append({
                                "filename": img.get("filename"),
                                "source_file": img_source_file,
                                "url": img.get("url"),
                                "score": img.get("score"),
                                "model_used": img.get("model_used", "hybrid"),
                                "detailed_description": img.get("detailed_description", ""),
                                "confidence": img.get("confidence", "medium"),
                                "priority": "primary" if (primary_file and (base_file in primary_file or primary_file in base_file)) else "secondary",
                                "page_number": img_page_num,
                                "page_rank": page_priority
                            })
                    else:
                        is_from_primary = primary_file and (base_file in primary_file or primary_file in base_file)
                        is_from_secondary = any(base_file in sf or sf in base_file for sf in secondary_files)
                        if is_from_primary or is_from_secondary:
                            is_primary_page_match = (img_page_num is not None and img_page_num in primary_pages)
                            filtered_clip_images.append({
                                "filename": img.get("filename"),
                                "source_file": img_source_file,
                                "url": img.get("url"),
                                "score": img.get("score"),
                                "model_used": img.get("model_used", "hybrid"),
                                "detailed_description": img.get("detailed_description", ""),
                                "confidence": img.get("confidence", "medium"),
                                "priority": "primary" if (is_from_primary and (not primary_pages or is_primary_page_match)) else "secondary",
                                "page_number": img_page_num,
                                "page_rank": 2 if is_primary_page_match else 1
                            })
                # If no text context picked a primary file, but we have images, derive primary_file from best image's source
                if (not primary_file) and filtered_clip_images:
                    try:
                        # Aggregate by exact source_file (json file name) using max score
                        by_src: Dict[str, float] = {}
                        for im in filtered_clip_images:
                            src = im.get("source_file") or ""
                            sc = float(im.get("score") or 0.0)
                            if src:
                                by_src[src] = max(sc, by_src.get(src, -1e9))
                        if by_src:
                            primary_file = max(by_src.items(), key=lambda t: t[1])[0]
                            # Filter images strictly to this file for source consistency
                            bf = primary_file.split("_page")[0] if "_page" in primary_file else primary_file.split(".")[0]
                            filtered_clip_images = [im for im in filtered_clip_images
                                                    if (im.get("source_file") and (bf in im["source_file"] or im["source_file"] in bf))]
                    except Exception:
                        pass
                if is_visual:
                    filtered_clip_images.sort(key=lambda x: (
                        -(x.get("page_rank") or 0),
                        (x.get("priority") != "primary"),
                        -float(x.get("score") or 0)
                    ))
                    images = filtered_clip_images[:6]
                else:
                    images = filtered_clip_images
            except Exception as e:
                print(f"[CLIP-Search-ERROR] {e}")
                import traceback
                traceback.print_exc()
                images = []
        else:
            images = []

        
        if is_visual:
           
            if images and not PAGE_LINK_IMAGES_ONLY:
                image_descriptions = []
                for img in images[:3]: 
                    desc = img.get("detailed_description", "")
                    if desc and desc != "Description unavailable":
                        image_descriptions.append(f"Image from {img.get('filename', 'unknown file')}: {desc}")
                
                if retrieved_text.strip():
                
                    combined_context = f"Text content:\n{retrieved_text}\n\nImage descriptions:\n" + "\n".join(image_descriptions)
                    llm_response = await _llm_call(combined_context, query + " (Focus on visual elements and provide details about the images shown)")
                else:
                   
                    if image_descriptions:
                        llm_response = await _llm_call("\n".join(image_descriptions), query + " (Based on the images found)")
                    else:
                        llm_response = "I found some relevant images for your query. Please review the images provided."
            else:
                if retrieved_text.strip():
                    llm_response = await _llm_call(retrieved_text, query)
                else:
                    return "I couldn't find any relevant images or content for your visual query."
        else:
            if not retrieved_text.strip():
                if images:
                    llm_response = "I found some relevant images for your query, but no text content was available."
                else:
                    return "The answer is not available in the provided context."
            else:
                # Defer LLM call until after page locking to use page-only text
                llm_response = None           
            chosen_image = None

            target_file = best_node_file or primary_file
            target_page = best_node_page or (primary_pages[0] if primary_pages else None)
            # Filter retrieved_text to same-page only
            if target_page is not None:
                filtered_text_nodes = [n for n in text_nodes if n.node.metadata.get("page_number") == target_page]
                retrieved_text = "\n\n".join([n.node.text for n in filtered_text_nodes if hasattr(n.node, 'text')])
                # If vector nodes missed this page (e.g., table-heavy pages), hydrate from JSON page content
                if not retrieved_text.strip() and target_file:
                    try:
                        from pathlib import Path as _P_hy
                        json_candidates_hy = [
                            config.OUTPUT_DIRECTORY / target_file,
                            (_P_hy(config.BASE_DIR).parent / "output" / target_file),
                        ]
                        def _table_text(it: Dict) -> str:
                            # prefer markdown/html/csv if present; else join cell texts
                            for k in ("md", "html", "csv"):
                                v = it.get(k)
                                if isinstance(v, str) and v.strip():
                                    return v
                            rows = it.get("rows") or []
                            parts = []
                            for r in rows:
                                try:
                                    parts.append("\t".join(str(c) for c in r))
                                except Exception:
                                    parts.append(" ".join(str(c) for c in r))
                            return "\n".join(parts)
                        page_text_hy = None
                        for jp in json_candidates_hy:
                            if not jp.exists():
                                continue
                            data_hy = _safe_json_load(jp) or {}
                            for p_hy in (data_hy.get("pages") or []):
                                try:
                                    pn_hy = int(p_hy.get("page") or p_hy.get("page_number") or -1)
                                except Exception:
                                    pn_hy = -1
                                if pn_hy != int(target_page):
                                    continue
                                chunks = []
                                if p_hy.get("text"):
                                    chunks.append(p_hy.get("text") or "")
                                if p_hy.get("md"):
                                    chunks.append(p_hy.get("md") or "")
                                for it in (p_hy.get("items") or []):
                                    t = (it.get("type") or it.get("item_type") or "").lower()
                                    if t in ("text", "heading"):
                                        chunks.append((it.get("value") or it.get("md") or ""))
                                    elif t == "table":
                                        chunks.append(_table_text(it))
                                page_text_hy = "\n".join([c for c in chunks if isinstance(c, str) and c.strip()])
                                break
                            if page_text_hy:
                                break
                        if page_text_hy and page_text_hy.strip():
                            retrieved_text = page_text_hy
                    except Exception:
                        pass
            # Robust override: if a page contains a HEADING matching the query (normalized),
            # force target_page to that page to avoid drift to TOC or references.
            try:
                if target_file and (query or '').strip():
                    import re as _re_fix
                    from pathlib import Path as _P_fix
                    q_full_ns_fix = _re_fix.sub(r"\s+", "", (query or "").lower())
                    def _norm_head2(s: str) -> str:
                        s = s or ""
                        s = _re_fix.sub(r"^\s*#+\s*", "", s)
                        s = _re_fix.sub(r"^\s*\d+\s*[\.:)\-]*\s*", "", s)
                        return _re_fix.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
                    qh2 = _norm_head2(query)
                    # Try both target_file and primary_file, with .json fallback if needed
                    cand_names = []
                    for nm in [target_file, primary_file]:
                        if not nm:
                            continue
                        cand_names.append(nm)
                        if not nm.endswith('.json'):
                            cand_names.append(f"{nm}.json")
                    seen = set()
                    json_candidates_fix = []
                    for nm in cand_names:
                        if nm in seen:
                            continue
                        seen.add(nm)
                        json_candidates_fix.append(config.OUTPUT_DIRECTORY / nm)
                        json_candidates_fix.append((_P_fix(config.BASE_DIR).parent / "output" / nm))
                    for jp in json_candidates_fix:
                        if not jp.exists():
                            continue
                        data_fix = _safe_json_load(jp) or {}
                        for p_fix in (data_fix.get("pages") or []):
                            try:
                                pn_fix = int(p_fix.get("page") or p_fix.get("page_number") or -1)
                            except Exception:
                                pn_fix = -1
                            if pn_fix <= 0:
                                continue
                            for it_fix in (p_fix.get("items") or []):
                                if (it_fix.get("type") or it_fix.get("item_type") or "").lower() == "heading":
                                    hv = (it_fix.get("value") or it_fix.get("md") or "")
                                    if qh2 and _norm_head2(hv) == qh2:
                                        target_page = pn_fix
                                        raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            # After final target_page is chosen, re-filter/re-hydrate text to the selected page
            try:
                if target_page is not None:
                    # Re-filter vector nodes
                    filtered_text_nodes2 = [n for n in text_nodes if n.node.metadata.get("page_number") == target_page]
                    retrieved_text = "\n\n".join([n.node.text for n in filtered_text_nodes2 if hasattr(n.node, 'text')])
                    if (not retrieved_text.strip()) and target_file:
                        # Hydrate from JSON using robust filename options
                        from pathlib import Path as _P_hy2
                        cand_names2 = []
                        for nm in [target_file, primary_file]:
                            if not nm:
                                continue
                            cand_names2.append(nm)
                            if not nm.endswith('.json'):
                                cand_names2.append(f"{nm}.json")
                        seen2 = set()
                        json_candidates_hy2 = []
                        for nm in cand_names2:
                            if nm in seen2:
                                continue
                            seen2.add(nm)
                            json_candidates_hy2.append(config.OUTPUT_DIRECTORY / nm)
                            json_candidates_hy2.append((_P_hy2(config.BASE_DIR).parent / "output" / nm))
                        def _table_text2(it: Dict) -> str:
                            for k in ("md", "html", "csv"):
                                v = it.get(k)
                                if isinstance(v, str) and v.strip():
                                    return v
                            rows = it.get("rows") or []
                            parts = []
                            for r in rows:
                                try:
                                    parts.append("\t".join(str(c) for c in r))
                                except Exception:
                                    parts.append(" ".join(str(c) for c in r))
                            return "\n".join(parts)
                        page_text_hy2 = None
                        for jp in json_candidates_hy2:
                            if not jp.exists():
                                continue
                            data_hy2 = _safe_json_load(jp) or {}
                            for p2 in (data_hy2.get("pages") or []):
                                try:
                                    pn2 = int(p2.get("page") or p2.get("page_number") or -1)
                                except Exception:
                                    pn2 = -1
                                if pn2 != int(target_page):
                                    continue
                                chunks = []
                                if p2.get("text"):
                                    chunks.append(p2.get("text") or "")
                                if p2.get("md"):
                                    chunks.append(p2.get("md") or "")
                                for it in (p2.get("items") or []):
                                    t = (it.get("type") or it.get("item_type") or "").lower()
                                    if t in ("text", "heading"):
                                        chunks.append((it.get("value") or it.get("md") or ""))
                                    elif t == "table":
                                        chunks.append(_table_text2(it))
                                page_text_hy2 = "\n".join([c for c in chunks if isinstance(c, str) and c.strip()])
                                break
                            if page_text_hy2:
                                break
                        if page_text_hy2 and page_text_hy2.strip():
                            retrieved_text = page_text_hy2
                    try:
                        print(f"[Retrieval] Final target_page={target_page} for {target_file} (primary={primary_file})")
                    except Exception:
                        pass
            except Exception:
                pass
           
            # Final same-page override: generic re-ranking of inline images on the selected page
            # using only query tokens/phrase, proximity to best-matching text, size, and light y-depth.
            try:
                if PAGE_LINK_IMAGES_ONLY and target_file and images:
                    sel_pg = images[0].get("page_number")
                    if sel_pg:
                        from pathlib import Path as _P3
                        import re as _re6, math as _math
                        json_candidates = [
                            config.OUTPUT_DIRECTORY / target_file,
                            (_P3(config.BASE_DIR).parent / "output" / target_file),
                        ]
                        for json_path in json_candidates:
                            if not json_path.exists():
                                continue
                            data = _safe_json_load(json_path) or {}
                            for p in (data.get("pages") or []):
                                try:
                                    pn = int(p.get("page") or p.get("page_number") or -1)
                                except Exception:
                                    pn = -1
                                if pn != sel_pg:
                                    continue
                                cand_imgs = [im for im in (p.get("images") or []) if (im.get("type") or im.get("img_type")) != "full_page_screenshot"]
                                if not cand_imgs:
                                    break
                                # Generic rescoring
                                # 1) Build query tokens and normalized phrase
                                # Tokens: include words (>2 chars) and any numeric tokens (e.g., step numbers like 10)
                                q_tokens = [t for t in _re6.findall(r"[A-Za-z0-9]+", (query or "").lower()) if (t.isdigit() or len(t) > 2)]
                                q_phrase_ns = _re6.sub(r"\s+", "", (query or "").lower())
                                def _bag_text(im: Dict) -> str:
                                    a = im.get("anchors") or {}
                                    ocr_txt = " ".join((e.get("text") or "") for e in (im.get("ocr") or []))
                                    return " ".join([
                                        ((a.get("heading") or {}).get("text") or ""),
                                        ((a.get("above_text") or {}).get("text") or ""),
                                        ((a.get("below_text") or {}).get("text") or ""),
                                        ocr_txt,
                                    ])
                                # 2) Find the best matching text item on the page
                                items = p.get("items") or []
                                def _tok(s: str):
                                    return [t for t in _re6.findall(r"[A-Za-z0-9]+", (s or "").lower()) if (t.isdigit() or len(t) > 2)]
                                def _overlap(tokens, text: str) -> int:
                                    if not text:
                                        return 0
                                    bag = set(_tok(text))
                                    return sum(1 for t in tokens if t in bag)
                                best_it = None; best_sc = -1
                                for it in items:
                                    if it.get("type") not in ("text","heading"):
                                        continue
                                    val = (it.get("value") or it.get("md") or "")
                                    # exact-phrase preference
                                    ns = _re6.sub(r"\s+", "", val.lower())
                                    sc = 1000 if (q_phrase_ns and q_phrase_ns in ns) else _overlap(q_tokens, val)
                                    if sc > best_sc:
                                        best_sc = sc; best_it = it
                                # 3) Score images generically
                                page_w = float(p.get("width") or 0.0); page_h = float(p.get("height") or 0.0)
                                # Precompute normalized depth ranks (top=0.0, bottom=1.0)
                                try:
                                    _ys = sorted([(float(im.get("y",0) or 0.0), im) for im in cand_imgs], key=lambda x: x[0])
                                    _n = max(1, len(_ys) - 1)
                                    _y_rank = {id(im): (i / _n) for i, (_, im) in enumerate(_ys)}
                                except Exception:
                                    _y_rank = {}
                                def _center(b):
                                    return (float(b.get("x",0) or 0.0) + float(b.get("w",0) or 0.0)/2.0,
                                            float(b.get("y",0) or 0.0) + float(b.get("h",0) or 0.0)/2.0)
                                def _score(im: Dict) -> float:
                                    bag = _bag_text(im)
                                    bag_ns = _re6.sub(r"\s+", "", (bag or "").lower())
                                    # phrase and token hits
                                    phrase_hit = 1.0 if (q_phrase_ns and q_phrase_ns in bag_ns) else 0.0
                                    token_hits = _overlap(q_tokens, bag)
                                    token_score = token_hits / max(1, len(q_tokens))
                                    # proximity: prefer below the best text if available
                                    prox = 0.0
                                    if best_it and best_it.get("bBox"):
                                        tx, ty = _center(best_it.get("bBox"))
                                        bb = {"x": im.get("y",0), "y": im.get("y",0), "w": im.get("width",0), "h": im.get("height",0)}
                                        ix = float(im.get("x",0) or 0.0) + float(im.get("width",0) or 0.0)/2.0
                                        iy = float(im.get("y",0) or 0.0) + float(im.get("height",0) or 0.0)/2.0
                                        dx = abs(ix - tx); dy = max(0.0, iy - ty)
                                        prox = 1.0 / (1.0 + dy + 0.25*dx)
                                    # size
                                    size_score = 0.0
                                    if page_w and page_h:
                                        area = float(im.get("width",0) or 0.0) * float(im.get("height",0) or 0.0)
                                        page_area = page_w * page_h
                                        if page_area > 0:
                                            ar = area / page_area
                                            wr = float(im.get("width",0) or 0.0) / page_w
                                            if ar < 0.01 or wr < 0.12:
                                                size_score -= 0.25
                                            else:
                                                size_score += min(0.15, ar * 0.6)
                                    # y-depth: light global bias + depth tie-breaker when semantics are weak
                                    ybias = 0.0
                                    if page_h:
                                        iy = float(im.get("y",0) or 0.0) + float(im.get("height",0) or 0.0)/2.0
                                        ybias = 0.08 * min(1.0, max(0.0, iy / page_h))
                                    depth_bonus = 0.0
                                    if phrase_hit == 0.0 and token_hits == 0:
                                        depth_bonus = 0.3 * float(_y_rank.get(id(im), 0.0))
                                    return 0.7*phrase_hit + 0.3*token_score + 0.25*prox + size_score + ybias + depth_bonus
                                # Rank by composite score; if scores are very close, prefer deeper image(s)
                                scored = [(im, _score(im)) for im in cand_imgs]
                                scored.sort(key=lambda t: t[1], reverse=True)
                                top_im, top_sc = scored[0]
                                # Semantic-only tie-break: if semantic signals are weak or essentially tied,
                                # prefer the deepest image on the page; if equal depth, prefer highest ordinal.
                                try:
                                    sems = []  # list of (img, semantic_score)
                                    for _im in cand_imgs:
                                        _bag = _bag_text(_im)
                                        _bag_ns = _re6.sub(r"\s+", "", (_bag or "").lower())
                                        _phrase_hit = 1.0 if (q_phrase_ns and q_phrase_ns in _bag_ns) else 0.0
                                        _tok_hits = _overlap(q_tokens, _bag)
                                        _tok_score = _tok_hits / max(1, len(q_tokens))
                                        _sem = 0.7 * _phrase_hit + 0.3 * _tok_score
                                        sems.append((_im, _sem))
                                    if sems:
                                        sems.sort(key=lambda t: t[1], reverse=True)
                                        max_sem = sems[0][1]
                                        second_sem = sems[1][1] if len(sems) > 1 else -1.0
                                        near_sem = [im for im, s in sems if (max_sem - s) <= 0.08]
                                        def _y_center(img: Dict) -> float:
                                            return float(img.get("y", 0) or 0.0) + float(img.get("height", 0) or 0.0) / 2.0
                                        def _yr(img: Dict) -> float:
                                            if _y_rank:
                                                return float(_y_rank.get(id(img), 0.0))
                                            yc = _y_center(img)
                                            return (yc / page_h) if page_h else yc
                                        def _ord(img: Dict) -> int:
                                            fn = (img.get("name") or img.get("filename") or "")
                                            m = _re6.search(r"_p(\d+)_([0-9]+)\.(png|jpg|jpeg)$", fn, flags=_re6.IGNORECASE)
                                            try:
                                                return int(m.group(2)) if m else -1
                                            except Exception:
                                                return -1
                                        if max_sem <= 0.4 or (len(sems) > 1 and (max_sem - second_sem) <= 0.08):
                                            if near_sem:
                                                near_sem_sorted = sorted(near_sem, key=lambda img: (_yr(img), _ord(img)), reverse=True)
                                                top_im = near_sem_sorted[0]
                                                # refresh top_sc for downstream closeness logic
                                                for _pair in scored:
                                                    if _pair[0] is top_im:
                                                        top_sc = _pair[1]
                                                        break
                                except Exception:
                                    pass
                                if len(scored) > 1:
                                    try:
                                        eps = 0.15  # broadened closeness threshold for depth-based tie-break
                                        near_tops = [im for im, sc in scored if (top_sc - sc) <= eps]
                                        if len(near_tops) > 1:
                                            def _y_center(img: Dict) -> float:
                                                return float(img.get("y", 0) or 0.0) + float(img.get("height", 0) or 0.0) / 2.0
                                            # Prefer the image deeper on the page; use precomputed normalized ranks when available
                                            def _yr(img: Dict) -> float:
                                                if _y_rank:
                                                    return float(_y_rank.get(id(img), 0.0))
                                                yc = _y_center(img)
                                                return (yc / page_h) if page_h else yc
                                            candidates = sorted(near_tops, key=_yr, reverse=True)
                                            top_im = candidates[0]
                                            # If still ambiguous by depth, prefer higher ordinal index in filename (e.g., _p18_3 over _p18_1)
                                            if len(candidates) > 1:
                                                try:
                                                    import re as _re_idx
                                                    def _ord(img: Dict) -> int:
                                                        fn = (img.get("name") or img.get("filename") or "")
                                                        m = _re_idx.search(r"_p(\d+)_([0-9]+)\.(png|jpg|jpeg)$", fn, flags=_re_idx.IGNORECASE)
                                                        return int(m.group(2)) if m else -1
                                                    # Among equal-depth tops (within tiny delta), pick max ordinal
                                                    d0 = _yr(top_im)
                                                    eq_depth = [im for im in candidates if abs(_yr(im) - d0) <= 1e-3]
                                                    if len(eq_depth) > 1:
                                                        top_im = max(eq_depth, key=_ord)
                                                except Exception:
                                                    pass
                                    except Exception:
                                        pass
                                nm = top_im.get("name") or top_im.get("filename")
                                if nm:
                                    # Update both images pool and chosen_image so later stages adopt this pick
                                    chosen_image = {
                                        "filename": nm,
                                        "url": f"/output/images/{nm}",
                                        "score": 1.0,
                                        "model_used": "generic-rescore",
                                        "detailed_description": "",
                                        "confidence": "high",
                                        "priority": "primary",
                                        "page_number": sel_pg,
                                        "page_rank": 2,
                                        "source_file": target_file,
                                    }
                                    images = [chosen_image]
                                break
            except Exception:
                pass

            # Ensure an image from the selected page is shown; if none match, use the page screenshot
            try:
                if target_file and (target_page is not None):
                    have_match = any((im.get("page_number") == target_page) for im in (images or []))
                    if (not images) or (not have_match):
                        from pathlib import Path as _P_img
                        fname_cur = target_file
                        prefix_cur = _derive_image_prefix(fname_cur)
                        shot_pref = _P_img(config.OUTPUT_DIRECTORY) / "images" / f"{prefix_cur}_page_{int(target_page)}.jpg"
                        shot_gen = _P_img(config.OUTPUT_DIRECTORY) / "images" / f"page_{int(target_page)}.jpg"
                        shot = shot_pref if shot_pref.exists() else shot_gen
                        if shot.exists():
                            sname = shot.name
                            images = [{
                                "filename": sname,
                                "url": f"/output/images/{sname}",
                                "score": 1.0,
                                "model_used": "page-screenshot",
                                "detailed_description": "",
                                "confidence": "high",
                                "priority": "primary",
                                "page_number": int(target_page),
                                "page_rank": 2
                            }]
                            try:
                                print(f"[Retrieval] Same-page image fallback -> screenshot {sname} for page {target_page}")
                            except Exception:
                                pass
            except Exception:
                pass

            if target_file:
                try:
                    from pathlib import Path as _Path
                   
                    import re
                    q_norm = re.sub(r"[^A-Za-z0-9]+", " ", query).strip().lower()
                    q_tokens = [t for t in re.findall(r"[A-Za-z0-9]+", q_norm) if len(t) > 2]
                    
                    q_tokens_orig = re.findall(r"[A-Za-z0-9]+", query or "")
                    salient_tokens = [
                        t for t in q_tokens_orig
                        if (t.isupper() and len(t) >= 3) or any(c.isdigit() for c in t)
                    ]
                 
                    seen_st = set()
                    salient_tokens = [t for t in salient_tokens if not (t.lower() in seen_st or seen_st.add(t.lower()))]
                    if q_tokens:
                        json_candidates = [
                            config.OUTPUT_DIRECTORY / target_file,
                            (_Path(config.BASE_DIR).parent / "output" / target_file),
                        ]
                        best_pg = None
                        best_hits = -1
                        best_total = 1
                        best_salient_hits = -1
                        best_salient_pg = None
                        q_phrase = " ".join(q_tokens)
                        for json_path in json_candidates:
                            if not json_path.exists():
                                continue
                            data = _safe_json_load(json_path) or {}
                          
                            import re as _re2
                            def _stem_token(t: str) -> str:
                                t = _re2.sub(r"[^a-z0-9]", "", (t or "").lower())
                                return t[:4] if len(t) >= 3 else t
                            q_lower_all = (query or "").lower()
                            q_tokens_all = [t for t in _re2.findall(r"[a-z0-9]+", q_lower_all) if len(t) > 2]
                            q_stems = [_stem_token(t) for t in q_tokens_all]
                            def _stems_from_text(text: str) -> set:
                                toks = [t for t in _re2.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2]
                                return set(_stem_token(t) for t in toks)
                            def _char_ngrams(s: str, n: int = 3) -> set:
                                s = _re2.sub(r"\s+", "", (s or "").lower())
                                return set(s[i:i+n] for i in range(max(0, len(s)-n+1))) if s else set()
                            q_ngrams = _char_ngrams(query or "", 3)
                            for p in data.get("pages", []):
                                # Prefer exact/normalized heading match first
                                def _normalize_heading(s: str) -> str:
                                    s = s or ""
                                    s = re.sub(r"^\s*#+\s*", "", s)  # drop markdown hashes
                                    s = re.sub(r"^\s*\d+\s*[\.):-]?\s*", "", s)  # drop leading numbering like "6." or "6)" or "6 -"
                                    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip().lower()
                                    return s
                                q_norm2 = _normalize_heading(query)
                                heading_match = False
                                for it in p.get("items", []):
                                    if it.get("type") == "heading":
                                        val = (it.get("value") or it.get("md") or "")
                                        v_norm1 = re.sub(r"[^A-Za-z0-9]+", " ", val).strip().lower()
                                        v_norm2 = _normalize_heading(val)
                                        if (q_norm and (q_norm in v_norm1 or v_norm1 in q_norm)) or (q_norm2 and (q_norm2 in v_norm2 or v_norm2 in q_norm2)):
                                            heading_match = True
                                            break
                                if heading_match:
                                    try:
                                        cand_pg = int(p.get("page") or p.get("page_number") or -1)
                                    except Exception:
                                        cand_pg = -1
                                    if cand_pg > 0:
                                        if best_pg is None or cand_pg < best_pg:
                                            best_pg = cand_pg
                                            best_hits = 999999  # strongest lock via heading
                                        continue
                                hits = 0
                                total = len(q_tokens)
                                
                                q_phrase_ns = re.sub(r"\s+", "", " ".join(q_tokens)) if q_tokens else ""
                              
                                ptext = (p.get("text") or "").lower()
                                ptext_ns = re.sub(r"\s+", "", ptext)
                                if ptext:
                                    hits += sum(1 for t in q_tokens if t in ptext)
                                    if q_phrase_ns and q_phrase_ns in ptext_ns:
                                        hits += total  
                                  
                                    page_stems = _stems_from_text(ptext)
                                    hits += sum(1 for st in q_stems if st and st in page_stems)
                                    
                                    pn = _char_ngrams(ptext, 3)
                                    if q_ngrams and pn:
                                        inter = len(q_ngrams & pn)
                                        union = len(q_ngrams | pn)
                                        sim = inter / union if union else 0.0
                                        if sim >= 0.45:
                                            hits += int(total + max(1, round(sim * 10)))
                             
                                for it in p.get("items", []):
                                    if it.get("type") in ("text", "heading"):
                                        val = (it.get("value") or it.get("md") or "").lower()
                                        if val:
                                            hits += sum(1 for t in q_tokens if t in val)
                                            val_ns = re.sub(r"\s+", "", val)
                                            if q_phrase_ns and q_phrase_ns in val_ns:
                                                hits += total
                                          
                                            item_stems = _stems_from_text(val)
                                            hits += sum(1 for st in q_stems if st and st in item_stems)
                                           
                                            inv = _char_ngrams(val, 3)
                                            if q_ngrams and inv:
                                                inter2 = len(q_ngrams & inv)
                                                union2 = len(q_ngrams | inv)
                                                sim2 = inter2 / union2 if union2 else 0.0
                                                if sim2 >= 0.45:
                                                    hits += int(total + max(1, round(sim2 * 10)))
                                
                                page_images_bag = []
                                for im in p.get("images", []) or []:
                                    anchors = im.get("anchors") or {}
                                    bag = " ".join([
                                        (anchors.get("heading") or {}).get("text") or "",
                                        (anchors.get("below_text") or {}).get("text") or "",
                                        (anchors.get("above_text") or {}).get("text") or "",
                                        " ".join((e.get("text") or "") for e in (im.get("ocr") or []))
                                    ]).lower()
                                    if bag:
                                        page_images_bag.append(bag)
                                        hits += sum(1 for t in q_tokens if t in bag)
                                        bag_stems = _stems_from_text(bag)
                                        hits += sum(1 for st in q_stems if st and st in bag_stems)
                                        ib = _char_ngrams(bag, 3)
                                        if q_ngrams and ib:
                                            inter3 = len(q_ngrams & ib)
                                            union3 = len(q_ngrams | ib)
                                            sim3 = inter3 / union3 if union3 else 0.0
                                            if sim3 >= 0.45:
                                                hits += int(max(1, round(sim3 * 8)))
                               
                                page_bag = ((p.get("text") or "") + "\n" + "\n".join(
                                    (it.get("value") or it.get("md") or "") for it in p.get("items", [])
                                )).lower()
                                page_bag_ns = re.sub(r"\s+", "", page_bag)
                          
                                exact_phrase_pg = None
                                if (query or "").strip():
                                    q_full_ns = re.sub(r"\s+", "", (query or "").lower())
                                    try:
                                        cand_pn = int(p.get("page") or p.get("page_number") or -1)
                                    except Exception:
                                        cand_pn = -1
                                    if q_full_ns and q_full_ns in page_bag_ns and cand_pn > 0:
                                        exact_phrase_pg = cand_pn
                               
                                s_hits = 0
                                if salient_tokens:
                                    for st in salient_tokens:
                                        try:
                                            in_text = re.search(fr"\b{re.escape(st)}\b", page_bag, flags=re.IGNORECASE) is not None
                                            in_imgs = any(
                                                re.search(fr"\b{re.escape(st)}\b", b, flags=re.IGNORECASE) is not None
                                                for b in page_images_bag
                                            ) if page_images_bag else False
                                            if in_text or in_imgs:
                                                s_hits += 1
                                        except Exception:
                                            if (st.lower() in page_bag) or any(st.lower() in b for b in page_images_bag):
                                                s_hits += 1
                                if s_hits > best_salient_hits:
                                    best_salient_hits = s_hits
                                    try:
                                        best_salient_pg = int(p.get("page") or p.get("page_number") or -1)
                                    except Exception:
                                        best_salient_pg = None
                                if hits > best_hits:
                                    best_hits = hits
                                    try:
                                        best_pg = int(p.get("page") or p.get("page_number") or -1)
                                    except Exception:
                                        best_pg = None
                                    best_total = max(best_total, total)
                                if exact_phrase_pg:
                                    best_pg = exact_phrase_pg
                                    best_hits = 999999
                                    best_total = max(best_total, total)
                        if salient_tokens and best_salient_hits > 0 and best_salient_pg:
                            target_page = best_salient_pg
                            strong_lock = True
                        elif best_pg and (best_hits == 99999 or best_hits >= 999999 or best_hits > 0):
                            target_page = best_pg
                            strong_lock = bool(best_hits >= 99999)
                        else:
                            strong_lock = False
                except Exception:
                    pass
            # Re-apply exact-HEADING lock AFTER heuristic page scoring to prevent override to TOC-like pages.
            # Only lock when a page has a heading whose normalized text exactly equals the query (numbers/punct removed).
            try:
                if target_file and (query or '').strip():
                    import re as _re_fix2
                    from pathlib import Path as _P_fix2
                    def _norm_head_fix2(s: str) -> str:
                        s = s or ""
                        s = _re_fix2.sub(r"^\s*#+\s*", "", s)               # drop markdown hashes
                        s = _re_fix2.sub(r"^\s*\d+\s*[\.:)\-]*\s*", "", s)  # drop leading numbering like "6." or "6)"
                        return _re_fix2.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
                    qh_fix2 = _norm_head_fix2(query)
                    if qh_fix2:
                        json_candidates_fix2 = [
                            config.OUTPUT_DIRECTORY / target_file,
                            (_P_fix2(config.BASE_DIR).parent / "output" / target_file),
                        ]
                        for jp2 in json_candidates_fix2:
                            if not jp2.exists():
                                continue
                            data_fix2 = _safe_json_load(jp2) or {}
                            for p_fix2 in (data_fix2.get("pages") or []):
                                try:
                                    pn_fix2 = int(p_fix2.get("page") or p_fix2.get("page_number") or -1)
                                except Exception:
                                    pn_fix2 = -1
                                if pn_fix2 <= 0:
                                    continue
                                for it_fix2 in (p_fix2.get("items") or []):
                                    if (it_fix2.get("type") or it_fix2.get("item_type")) == "heading":
                                        hv = (it_fix2.get("value") or it_fix2.get("md") or "")
                                        if _norm_head_fix2(hv) == qh_fix2:
                                            target_page = pn_fix2
                                            raise StopIteration
            except StopIteration:
                pass
            except Exception:
                pass
            if target_file and target_page is not None:
                candidate_pages = [int(target_page)]  # strictly lock to the detected page only
                candidate_pages = [p for p in sorted(set(candidate_pages)) if p > 0]

                clip_by_page: Dict[int, List[Dict]] = {}
                if PAGE_LINK_IMAGES_ONLY:
                    clip_by_page = {int(target_page): []}
                else:
                    try:
                        from app.vector_db.upsert_image import search_images_on_page
                        for pnum in candidate_pages:
                            try:
                                clip_by_page[pnum] = await search_images_on_page(query, index_name_clean, target_file, int(pnum), top_k=5)
                            except Exception:
                                clip_by_page[pnum] = []
                    except Exception:
                        clip_by_page = {int(target_page): []}

                def _is_inline_filename(fn: Optional[str]) -> bool:
                    if not fn:
                        return False
                    return bool(re.search(r"(?:[A-Za-z0-9._-]+_)?img_p\d+_\d+\.(png|jpg|jpeg)$", fn))

                exact_matches = [
                    im for im in images
                    if (im.get("source_file") == target_file)
                    and (int(im.get("page_number") or -1) in candidate_pages)
                    and _is_inline_filename(im.get("filename"))
                ]
                exact_pool = list(exact_matches)
                for lst in clip_by_page.values():
                    exact_pool.extend(lst)
                seen = set()
                deduped = []
                for im in exact_pool:
                    key = im.get("filename")
                    if key and key not in seen:
                        seen.add(key)
                        deduped.append(im)
                if deduped:
                    deduped.sort(key=lambda x: -float(x.get("score") or 0))
                    chosen_image = deduped[0]

                if chosen_image:
                    try:
                        ch_page = int(chosen_image.get("page_number") or -1)
                    except Exception:
                        ch_page = -1
                    if target_file and ch_page in candidate_pages:
                        try:
                            from pathlib import Path as _Path
                            import re, math
                            toks = re.findall(r"[A-Za-z0-9]+", query.lower())
                            q_alpha = [t for t in toks if any(c.isalpha() for c in t) and len(t) > 2]
                            q_nums = [t for t in toks if t.isdigit()]
                            q_tokens = q_alpha + q_nums
                            q_text = "".join(q_tokens)
                            clip_map = {}
                            for pg, lst in (clip_by_page or {}).items():
                                for im in lst or []:
                                    fn = im.get("filename")
                                    if fn:
                                        clip_map[fn] = max(float(clip_map.get(fn, 0.0)), float(im.get("score") or 0))

                            json_candidates = [
                                config.OUTPUT_DIRECTORY / target_file,
                                (_Path(config.BASE_DIR).parent / "output" / target_file),
                            ]
                            for json_path in json_candidates:
                                if not json_path.exists():
                                    continue
                                data = _safe_json_load(json_path) or {}
                                pages = data.get("pages", [])
                                target_page_obj = None
                                for p in pages:
                                    try:
                                        pn = int(p.get("page") or p.get("page_number") or -1)
                                    except Exception:
                                        pn = -1
                                    if pn == ch_page:
                                        target_page_obj = p
                                        break
                                if not target_page_obj:
                                    continue
                                # Rebuild a page-only text to avoid cross-page leakage in the final answer
                                page_only_text_parts = []
                                try:
                                    ptxt = (target_page_obj.get("text") or "").strip()
                                    if ptxt:
                                        page_only_text_parts.append(ptxt)
                                    for it in target_page_obj.get("items", []) or []:
                                        if it.get("type") in ("text", "heading"):
                                            v = (it.get("value") or it.get("md") or "").strip()
                                            if v:
                                                page_only_text_parts.append(v)
                                except Exception:
                                    pass
                                def token_overlap(text: str) -> int:
                                    if not text:
                                        return 0
                                    tt = re.findall(r"[A-Za-z0-9]+", text.lower())
                                    hits = 0
                                    for t in q_alpha:
                                        if t in tt:
                                            hits += 1
                                    for n in q_nums:
                                        if n in tt:
                                            hits += 1
                                    return hits
                                items = target_page_obj.get("items", [])
                                best_item = None
                                best_ov = -1
                                for it in items:
                                    if it.get("type") not in ("text", "heading"):
                                        continue
                                    val = (it.get("value") or it.get("md") or "")
                                    ov = token_overlap(val)
                                    if ov > best_ov:
                                        best_ov = ov
                                        best_item = it
                                headings = [it for it in items if it.get("type") == "heading" and it.get("bBox")]
                                headings.sort(key=lambda h: (h["bBox"].get("y", 0), h["bBox"].get("x", 0)))
                                page_w = float(target_page_obj.get("width") or 0.0)
                                page_h = float(target_page_obj.get("height") or 0.0)
                                region_lb = None
                                region_ub = None
                                if best_item and best_item.get("type") == "heading" and best_item.get("bBox"):
                                    by = best_item["bBox"].get("y", 0)
                                    region_lb = by
                                    ny = None
                                    for h in headings:
                                        if h is best_item:
                                            continue
                                        hy = h["bBox"].get("y", 0)
                                        if hy > by and (ny is None or hy < ny):
                                            ny = hy
                                    region_ub = ny if ny is not None else page_h if page_h else None
                                def center(b):
                                    return (b.get("x", 0) + b.get("w", 0)/2.0, b.get("y", 0) + b.get("h", 0)/2.0)
                                def image_score(img: Dict) -> float:
                                    anchors = img.get("anchors") or {}
                                    heading_t = (anchors.get("heading") or {}).get("text") if isinstance(anchors, dict) else None
                                    above_t = (anchors.get("above_text") or {}).get("text") if isinstance(anchors, dict) else None
                                    below_t = (anchors.get("below_text") or {}).get("text") if isinstance(anchors, dict) else None
                                    ocr_entries = img.get("ocr") or []
                                    ocr_text = " ".join((e.get("text") or "") for e in ocr_entries)
                                    bag = " ".join([t for t in [heading_t, below_t, above_t, ocr_text] if t]).lower()
                                    ov = 0.0
                                    if q_tokens and bag:
                                        token_hits = 0
                                        for t in q_alpha:
                                            if t in bag:
                                                token_hits += 1
                                        for n in q_nums:
                                            if re.search(fr"\b{re.escape(n)}\b", bag):
                                                token_hits += 1
                                        ov = token_hits / max(1, len(q_tokens))
                                        if q_text and q_text in bag.replace(" ", ""):
                                            ov = min(1.0, ov + 0.3)
                                    fn2 = img.get("name") or img.get("filename")
                                    clip_s = float(clip_map.get(fn2, 0.0))
                                    prox = 0.0
                                    if best_item and best_item.get("bBox"):
                                        tx, ty = center(best_item["bBox"])
                                        bb = {"x": img.get("x",0), "y": img.get("y",0), "w": img.get("width",0), "h": img.get("height",0)}
                                        ix, iy = center(bb)
                                        d = math.sqrt((ix - tx)**2 + (iy - ty)**2)
                                        prox = 1.0 / (1.0 + d)
                                        if iy >= ty:
                                            prox = min(1.0, prox + 0.05)
                                        if abs(iy - ty) <= 150:
                                            prox = min(1.0, prox + 0.08)
                                    region_bonus = 0.0
                                    if region_lb is not None:
                                        iy_top = img.get("y", 0)
                                        ub = region_ub if region_ub is not None else (page_h or 0)
                                        if iy_top >= region_lb and (ub == 0 or iy_top < ub):
                                            region_bonus = 0.12
                                        else:
                                            region_bonus = -0.10
                                    size_bonus = 0.0
                                    if page_w and page_h:
                                        area = float(img.get("width", 0) or 0) * float(img.get("height", 0) or 0)
                                        page_area = page_w * page_h
                                        if page_area > 0:
                                            area_ratio = min(1.0, area / page_area)
                                            size_bonus = max(0.0, 0.08 * (1.0 - area_ratio))
                                    return 0.50 * ov + 0.30 * clip_s + 0.20 * prox + region_bonus + size_bonus
                                imgs = target_page_obj.get("images", [])
                                inline_imgs = [i for i in imgs if (i.get("type") or i.get("img_type")) != "full_page_screenshot"]
                                def _img_index_local(img: Dict) -> int:
                                    import re as _re
                                    fname = (img.get("name") or img.get("filename") or "")
                                    m = _re.search(r"_p(\d+)_([0-9]+)\\.png$|_p(\d+)_([0-9]+)\.png$", fname)
                                    if not m:
                                        return -1
                                    try:
                                        return int(m.group(2) or m.group(4) or -1)
                                    except Exception:
                                        return -1
                                # Robust on-page mapping: tie each image to its nearest relevant text (above/below)
                                if inline_imgs:
                                    try:
                                        import math as _math
                                        import re as _re4

                                        def _tok(s: str) -> List[str]:
                                            return [t for t in _re4.findall(r"[A-Za-z0-9]+", (s or "").lower()) if len(t) > 2]

                                        def _overlap(tokens: List[str], text: str) -> int:
                                            if not text:
                                                return 0
                                            bag = set(_tok(text))
                                            return sum(1 for t in tokens if t in bag)

                                        def _center_x(b):
                                            return float((b or {}).get("x", 0.0)) + float((b or {}).get("w", 0.0)) / 2.0

                                        def _center_y(b):
                                            return float((b or {}).get("y", 0.0)) + float((b or {}).get("h", 0.0)) / 2.0

                                        def _bbox(img: Dict) -> Dict[str, float]:
                                            return {
                                                "x": float(img.get("x", 0) or 0.0),
                                                "y": float(img.get("y", 0) or 0.0),
                                                "w": float(img.get("width", 0) or 0.0),
                                                "h": float(img.get("height", 0) or 0.0),
                                            }

                                        # Build text pool
                                        text_items = [it for it in items if it.get("type") in ("text", "heading") and it.get("bBox")]

                                        # Precompute tokens
                                        q_all_tokens = q_alpha + q_nums
                                        q_phrase_norm = _re4.sub(r"\s+", "", (" ".join(q_all_tokens))).lower()
                                        q_full_norm = _re4.sub(r"\s+", "", (query or "").lower())

                                        # Helper: trivial number filter (e.g., page number only)
                                        def _is_trivial_number(val: str, page_no: Optional[int]) -> bool:
                                            v = (val or "").strip()
                                            if not v:
                                                return False
                                            if v.isdigit():
                                                try:
                                                    if page_no is not None and int(v) == int(page_no):
                                                        return True
                                                except Exception:
                                                    pass
                                                return len(v) <= 2
                                            return False

                                        try:
                                            _pg_no_local = int(target_page_obj.get("page") or target_page_obj.get("page_number") or -1)
                                        except Exception:
                                            _pg_no_local = None

                                        # Identify candidate texts likely describing the images (exclude headings and trivial numbers)
                                        min_img_y = min(float(im.get("y", 0) or 0.0) for im in inline_imgs)
                                        candidate_texts = []
                                        for it in items:
                                            if it.get("type") != "text":
                                                continue
                                            if not it.get("bBox"):
                                                continue
                                            val_txt = (it.get("value") or it.get("md") or "").strip()
                                            if _is_trivial_number(val_txt, _pg_no_local):
                                                continue
                                            ty = float((it.get("bBox") or {}).get("y", 0) or 0.0)
                                            if ty >= (min_img_y - 5):
                                                candidate_texts.append(it)
                                        candidate_texts.sort(key=lambda t: (float((t.get("bBox") or {}).get("y", 0) or 0.0), float((t.get("bBox") or {}).get("x", 0) or 0.0)))
                                        ordered_images_by_y = sorted(inline_imgs, key=lambda im: (float(im.get("y", 0) or 0.0), float(im.get("x", 0) or 0.0)))

                                        # If the query mentions a step number, prefer that ordinal image when available
                                        step_index = None
                                        try:
                                            m_step = _re4.search(r"\bstep\s*(\d+)\b", (query or ""), flags=_re4.IGNORECASE)
                                            if m_step:
                                                step_val = int(m_step.group(1))
                                                if step_val >= 1:
                                                    step_index = step_val - 1
                                        except Exception:
                                            step_index = None

                                        # Optional best-item geometry
                                        best_bb = (best_item or {}).get("bBox") or {}
                                        best_x = _center_x(best_bb) if best_bb else None
                                        best_y = _center_y(best_bb) if best_bb else None

                                        page_w = float(target_page_obj.get("width") or 0.0)
                                        page_h = float(target_page_obj.get("height") or 0.0)

                                        def _ocr_text(im: Dict) -> str:
                                            return " ".join((e.get("text") or "") for e in (im.get("ocr") or []))

                                        def _anchor_texts(im: Dict) -> List[str]:
                                            a = im.get("anchors") or {}
                                            return [
                                                ((a.get("heading") or {}).get("text") or ""),
                                                ((a.get("above_text") or {}).get("text") or ""),
                                                ((a.get("below_text") or {}).get("text") or ""),
                                            ]

                                        def _nearest_text_scores(img: Dict) -> Dict[str, Any]:
                                            ib = _bbox(img)
                                            ix = _center_x(ib)
                                            iy = _center_y(ib)
                                            best_above = None
                                            best_below = None
                                            best_above_d = 1e9
                                            best_below_d = 1e9
                                            for it in text_items:
                                                tb = it.get("bBox") or {}
                                                tx = _center_x(tb)
                                                ty = _center_y(tb)
                                                dx = abs(ix - tx)
                                                dy = iy - ty
                                                # Prefer horizontal overlap, else use dx penalty
                                                horiz_overlap = not (
                                                    (tb.get("x", 0) + tb.get("w", 0) < ib.get("x", 0)) or (ib.get("x", 0) + ib.get("w", 0) < tb.get("x", 0))
                                                )
                                                penalty = 0.0 if horiz_overlap else min(200.0, dx)
                                                if dy > 0:  # text above image
                                                    d = dy + 0.3 * penalty
                                                    if d < best_above_d:
                                                        best_above_d = d
                                                        best_above = it
                                                else:  # text below image
                                                    d = (-dy) + 0.4 * penalty
                                                    if d < best_below_d:
                                                        best_below_d = d
                                                        best_below = it
                                            return {
                                                "above": (best_above, best_above_d),
                                                "below": (best_below, best_below_d),
                                                "ix": ix,
                                                "iy": iy,
                                            }

                                        def _final_score(img: Dict) -> float:
                                            ib = _bbox(img)
                                            # Base image_score provides region/size/prox + query token hits in bag
                                            base = image_score(img)
                                            # Anchor/ OCR overlap
                                            bag_txt = " ".join(_anchor_texts(img) + [_ocr_text(img)])
                                            bag_hits = _overlap(q_all_tokens, bag_txt)
                                            # Fast-path: if the bag contains the full normalized query or phrase, pick this image
                                            try:
                                                bag_ns = _re4.sub(r"\s+", "", bag_txt.lower())
                                                if (q_phrase_norm and q_phrase_norm in bag_ns) or (len(q_full_norm) >= 10 and q_full_norm in bag_ns):
                                                    return 10_000.0  # force-select
                                            except Exception:
                                                pass
                                            # Nearest text overlaps
                                            near = _nearest_text_scores(img)
                                            above, da = near["above"]
                                            below, db = near["below"]
                                            above_hits = _overlap(q_all_tokens, (above or {}).get("value") or (above or {}).get("md") or "") if above else 0
                                            below_hits = _overlap(q_all_tokens, (below or {}).get("value") or (below or {}).get("md") or "") if below else 0
                                            # Proximity weights (closer text -> higher)
                                            wa = 1.0 / (1.0 + max(5.0, da)) if above else 0.0
                                            wb = 1.0 / (1.0 + max(5.0, db)) if below else 0.0
                                            text_score = (wa * above_hits) + (wb * below_hits)
                                            # Alignment with best_item (if any): prefer horizontally closer image
                                            align_bonus = 0.0
                                            if best_x is not None:
                                                dx = abs(near["ix"] - best_x)
                                                align_bonus = max(0.0, 1.0 - min(1.0, dx / max(50.0, page_w * 0.25))) * 0.2
                                            # Size emphasis for multiple images in a row (favor mid/large, avoid tiny icons)
                                            size_bonus = 0.0
                                            if page_w and page_h:
                                                area = float(img.get("width", 0) or 0.0) * float(img.get("height", 0) or 0.0)
                                                page_area = page_w * page_h
                                                if page_area > 0:
                                                    ar = area / page_area
                                                    wr = float(img.get("width", 0) or 0.0) / page_w
                                                    if ar < 0.01 or wr < 0.12:
                                                        size_bonus -= 0.25
                                                    else:
                                                        size_bonus += min(0.15, ar * 0.6)
                                            # Strong boost if anchors explicitly reference query tokens
                                            anchor_boost = 0.0
                                            if bag_hits > 0:
                                                anchor_boost = min(0.35, 0.12 * bag_hits)
                                            # Compose final
                                            return 0.45 * text_score + 0.25 * (bag_hits) + 0.20 * base + align_bonus + size_bonus + anchor_boost

                                        # Prefer images aligned to the most relevant text item for this query
                                        best_text = None
                                        best_text_score = -1
                                        for it in text_items:
                                            score = _overlap(q_all_tokens, (it.get("value") or it.get("md") or ""))
                                            if score > best_text_score:
                                                best_text_score = score
                                                best_text = it

                                        # If a very specific text match is found, anchor selection to nearest image below that text,
                                        # but first try ordinal mapping: map best-matching text index to image index.
                                        if best_text and best_text_score > 0:
                                            try:
                                                # Ordinal mapping across candidate texts/images (fixes page-4 triple mapping)
                                                if candidate_texts:
                                                    try:
                                                        idx_text = next(i for i, t in enumerate(candidate_texts) if t is best_text)
                                                    except StopIteration:
                                                        idx_text = None
                                                    # Step-based override if present
                                                    desired_idx = step_index if (step_index is not None) else idx_text
                                                    if desired_idx is not None and ordered_images_by_y:
                                                        desired_idx = max(0, min(desired_idx, len(ordered_images_by_y) - 1))
                                                        mapped = ordered_images_by_y[desired_idx]
                                                        nm = mapped.get("name") or mapped.get("filename")
                                                        if nm and nm != (chosen_image or {}).get("filename"):
                                                            chosen_image = {
                                                                "filename": nm,
                                                                "url": f"/output/images/{nm}",
                                                                "score": 1.0,
                                                                "model_used": "ordinal-map",
                                                                "detailed_description": "",
                                                                "confidence": "high",
                                                                "priority": "primary",
                                                                "page_number": ch_page,
                                                                "page_rank": 2
                                                            }
                                                            break

                                                tbb = best_text.get("bBox") or {}
                                                tx = _center_x(tbb); ty = _center_y(tbb)
                                                # filter images below or very close to the text
                                                below_imgs = [im for im in inline_imgs if float(im.get("y", 0) or 0.0) >= (float(tbb.get("y", 0) or 0.0) - 5)]
                                                pool = below_imgs if below_imgs else inline_imgs
                                                # Score by (1) anchor/OCR token overlap, (2) proximity to the best text, (3) size emphasis
                                                def _score_below(im):
                                                    bb = _bbox(im)
                                                    ix = _center_x(bb); iy = _center_y(bb)
                                                    dx = abs(ix - tx); dy = max(0.0, iy - ty)
                                                    prox = 1.0 / (1.0 + dy + 0.25 * dx)
                                                    bag_txt = " ".join(_anchor_texts(im) + [_ocr_text(im)])
                                                    hits = _overlap(q_all_tokens, bag_txt)
                                                    bag_norm = hits / max(1, len(q_all_tokens))
                                                    try:
                                                        bag_ns = re.sub(r"\s+", "", bag_txt.lower())
                                                        phrase_boost = 0.5 if q_text and (q_text in bag_ns) else 0.0
                                                    except Exception:
                                                        phrase_boost = 0.0
                                                    bag_score = min(1.0, bag_norm + phrase_boost)
                                                    # size
                                                    size_score = 0.0
                                                    if page_w and page_h:
                                                        area = float(im.get("width",0) or 0.0) * float(im.get("height",0) or 0.0)
                                                        page_area = page_w * page_h
                                                        if page_area > 0:
                                                            ar = area / page_area
                                                            wr = float(im.get("width",0) or 0.0) / page_w
                                                            if ar < 0.01 or wr < 0.12:
                                                                size_score -= 0.25
                                                            else:
                                                                size_score += min(0.15, ar * 0.6)
                                                    # No query keyword biases; apply only a light y-depth bias
                                                    ybias = 0.0
                                                    if page_h:
                                                        y_ratio = min(1.0, max(0.0, iy / page_h))
                                                        ybias = 0.05 * y_ratio
                                                    return 0.6 * bag_score + 0.2 * prox + 0.15 * size_score + ybias
                                                pick = sorted(pool, key=lambda im: -_score_below(im))[0]
                                                name = pick.get("name") or pick.get("filename")
                                                if name and name != (chosen_image or {}).get("filename"):
                                                    chosen_image = {
                                                        "filename": name,
                                                        "url": f"/output/images/{name}",
                                                        "score": 1.0,
                                                        "model_used": "text-anchor-nearest",
                                                        "detailed_description": "",
                                                        "confidence": "high",
                                                        "priority": "primary",
                                                        "page_number": ch_page,
                                                        "page_rank": 2
                                                    }
                                                break
                                            except Exception:
                                                pass

                            # (Final answer building moved to a safer location after image selection.)

                                        # Fall back to best_item-based below-region ordering when no earlier choice was made
                                        if not chosen_image:
                                            ordered = inline_imgs
                                            if best_item and best_item.get("bBox"):
                                                by_top = float((best_item.get("bBox") or {}).get("y", 0) or 0.0)
                                                below = [im for im in inline_imgs if float(im.get("y", 0) or 0.0) >= (by_top + 5)]
                                                ordered = below if below else inline_imgs
                                            # Score all candidates and pick best
                                            scored = [(_final_score(im), im) for im in ordered]
                                            scored.sort(key=lambda x: x[0], reverse=True)
                                            pick = scored[0][1]
                                            name = pick.get("name") or pick.get("filename")
                                            if name and name != (chosen_image or {}).get("filename"):
                                                chosen_image = {
                                                    "filename": name,
                                                    "url": f"/output/images/{name}",
                                                    "score": 1.0,
                                                    "model_used": "text-nearest",
                                                    "detailed_description": "",
                                                    "confidence": "high",
                                                    "priority": "primary",
                                                    "page_number": ch_page,
                                                    "page_rank": 2
                                                }
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                if not chosen_image and not PAGE_LINK_IMAGES_ONLY:
                    def _num_key(fname: Optional[str]) -> int:
                        if not fname:
                            return 9999
                        import re
                        m = re.search(r"_p(\d+)_([0-9]+)\\.png$|_p(\d+)_([0-9]+)\.png$", fname)
                        if m:
                            try:
                                idx = int(m.group(2) or m.group(4) or 9999)
                            except Exception:
                                idx = 9999
                            return idx
                        return 9999
                    def _hits(s: str) -> int:
                        return sum(1 for t in q_tokens if t in (s or "").lower())
                    best = None
                    for pg, lst in clip_by_page.items():
                        for im in lst or []:
                            cap = (im.get("caption") or im.get("detailed_description") or "").lower()
                            h = _hits(cap)
                            if h > 0:
                                sc = float(im.get("score") or 0)
                                fname = im.get("filename") or ""
                                if not _is_inline_filename(fname):
                                    continue
                                cand = (h, sc, -_num_key(fname), im)
                                if best is None or cand > best:
                                    best = cand
                    if best is not None:
                        chosen_image = best[-1]

                if not chosen_image:
                    try:
                        from pathlib import Path as _Path
                        json_candidates = [
                            config.OUTPUT_DIRECTORY / target_file,
                            (_Path(config.BASE_DIR).parent / "output" / target_file),
                        ]
                        best_pick = None
                        best_pick_score = float("-inf")
                        def _img_index(img: Dict) -> int:
                            import re
                            fname = (img.get("name") or img.get("filename") or "")
                            m = re.search(r"_p(\d+)_([0-9]+)\\.png$|_p(\d+)_([0-9]+)\.png$", fname)
                            if not m:
                                return 9999
                            try:
                                return int(m.group(2) or m.group(4) or 9999)
                            except Exception:
                                return 9999

                        for json_path in json_candidates:
                            if not json_path.exists():
                                continue
                            data = _safe_json_load(json_path) or {}
                            pages = data.get("pages", [])
                            for p in pages:
                                pnum = p.get("page") or p.get("page_number")
                                try:
                                    pn = int(pnum or -1)
                                except Exception:
                                    pn = -1
                                if pn in candidate_pages:
                                    imgs = p.get("images", [])
                                    inline_imgs = [i for i in imgs if (i.get("type") or i.get("img_type")) != "full_page_screenshot"]
                                    items = p.get("items", [])
                                    import re, math
                                    toks = re.findall(r"[A-Za-z0-9]+", query.lower())
                                    q_alpha = [t for t in toks if any(c.isalpha() for c in t) and len(t) > 2]
                                    q_nums = [t for t in toks if t.isdigit()]
                                    q_tokens = q_alpha + q_nums
                                    q_text = "".join(q_tokens)
                                    def token_overlap(text: str) -> int:
                                        if not text:
                                            return 0
                                        tt = re.findall(r"[A-Za-z0-9]+", (text or "").lower())
                                        hits = 0
                                        for t in q_alpha:
                                            if t in tt:
                                                hits += 1
                                        for n in q_nums:
                                            if n in tt:
                                                hits += 1
                                        return hits
                                    best_item = None
                                    best_overlap = -1
                                    for it in items:
                                        if it.get("type") not in ("text", "heading"):
                                            continue
                                        val = (it.get("value") or it.get("md") or "")
                                        ov = token_overlap(val)
                                        if ov > best_overlap:
                                            best_overlap = ov
                                            best_item = it
                                    headings = [it for it in items if it.get("type") == "heading" and it.get("bBox")]
                                    headings.sort(key=lambda h: (h["bBox"].get("y", 0), h["bBox"].get("x", 0)))
                                    page_w = float(p.get("width") or 0.0)
                                    page_h = float(p.get("height") or 0.0)
                                    region_lb = None
                                    region_ub = None
                                    if best_item and best_item.get("type") == "heading" and best_item.get("bBox"):
                                        by = best_item["bBox"].get("y", 0)
                                        region_lb = by
                                        ny = None
                                        for h in headings:
                                            if h is best_item:
                                                continue
                                            hy = h["bBox"].get("y", 0)
                                            if hy > by and (ny is None or hy < ny):
                                                ny = hy
                                        region_ub = ny if ny is not None else page_h if page_h else None

                                    def center(b):
                                        return (b.get("x", 0) + b.get("w", 0)/2.0, b.get("y", 0) + b.get("h", 0)/2.0)
                                    clip_map = {}
                                    for pg, lst in clip_by_page.items():
                                        for im in lst or []:
                                            fn = im.get("filename")
                                            if fn:
                                                clip_map[fn] = max(float(clip_map.get(fn, 0.0)), float(im.get("score") or 0))

                                    def image_score(img: Dict) -> float:
                                        anchors = img.get("anchors") or {}
                                        heading_t = (anchors.get("heading") or {}).get("text") if isinstance(anchors, dict) else None
                                        above_t = (anchors.get("above_text") or {}).get("text") if isinstance(anchors, dict) else None
                                        below_t = (anchors.get("below_text") or {}).get("text") if isinstance(anchors, dict) else None
                                        ocr_entries = img.get("ocr") or []
                                        ocr_text = " ".join((e.get("text") or "") for e in ocr_entries)
                                        bag_text = " ".join([t for t in [heading_t, below_t, above_t, ocr_text] if t])
                                        bag = bag_text.lower()
                                        ov = 0.0
                                        if q_tokens and bag:
                                            token_hits = 0
                                            for t in q_alpha:
                                                if t in bag:
                                                    token_hits += 1
                                            for n in q_nums:
                                                if re.search(fr"\b{re.escape(n)}\b", bag):
                                                    token_hits += 1
                                            ov = token_hits / max(1, len(q_tokens))
                                            if q_text and q_text in bag.replace(" ", ""):
                                                ov = min(1.0, ov + 0.3)
                                        fn2 = img.get("name") or img.get("filename")
                                        clip_s = float(clip_map.get(fn2, 0.0))
                                        prox = 0.0
                                        if best_item and best_item.get("bBox"):
                                            tx, ty = center(best_item["bBox"])
                                            bb = {"x": img.get("x",0), "y": img.get("y",0), "w": img.get("width",0), "h": img.get("height",0)}
                                            ix, iy = center(bb)
                                            d = math.sqrt((ix - tx)**2 + (iy - ty)**2)
                                            prox = 1.0 / (1.0 + d)  # closer -> higher
                                            if iy >= ty:
                                                prox = min(1.0, prox + 0.05)  # prefer below text
                                            if abs(iy - ty) <= 150:
                                                prox = min(1.0, prox + 0.08)
                                        region_bonus = 0.0
                                        if region_lb is not None:
                                            iy_top2 = img.get("y", 0)
                                            ub = region_ub if region_ub is not None else (page_h or 0)
                                            if iy_top2 >= region_lb and (ub == 0 or iy_top2 < ub):
                                                region_bonus = 0.12
                                            else:
                                                region_bonus = -0.10
                                        size_bonus = 0.0
                                        if page_w and page_h:
                                            area = float(img.get("width", 0) or 0) * float(img.get("height", 0) or 0)
                                            page_area = page_w * page_h
                                            if page_area > 0:
                                                area_ratio = min(1.0, area / page_area)
                                                size_bonus = max(0.0, 0.08 * (1.0 - area_ratio))
                                        return 0.50 * ov + 0.30 * clip_s + 0.20 * prox + region_bonus + size_bonus

                                    if inline_imgs:
                                        try:
                                            import re as _re4
                                            # Prepare tokens and helpers
                                            def _tok(s: str) -> List[str]:
                                                return [t for t in _re4.findall(r"[A-Za-z0-9]+", (s or "").lower()) if len(t) > 2]
                                            def _overlap(tokens: List[str], text: str) -> int:
                                                if not text:
                                                    return 0
                                                bag = set(_tok(text))
                                                return sum(1 for t in tokens if t in bag)
                                            q_all_tokens = q_alpha + q_nums
                                            q_phrase_norm = _re4.sub(r"\s+", "", (" ".join(q_all_tokens))).lower()
                                            q_full_norm = _re4.sub(r"\s+", "", (query or "").lower())

                                            def _bbox(img: Dict) -> Dict[str, float]:
                                                return {
                                                    "x": float(img.get("x", 0) or 0.0),
                                                    "y": float(img.get("y", 0) or 0.0),
                                                    "w": float(img.get("width", 0) or 0.0),
                                                    "h": float(img.get("height", 0) or 0.0),
                                                }
                                            def _center_x(b):
                                                return float((b or {}).get("x", 0.0)) + float((b or {}).get("w", 0.0)) / 2.0
                                            def _center_y(b):
                                                return float((b or {}).get("y", 0.0)) + float((b or {}).get("h", 0.0)) / 2.0

                                            # Build candidate texts near image region (exclude trivial numbers)
                                            def _is_trivial_number(val: str, page_no: Optional[int]) -> bool:
                                                v = (val or "").strip()
                                                if not v:
                                                    return False
                                                if v.isdigit():
                                                    try:
                                                        if page_no is not None and int(v) == int(page_no):
                                                            return True
                                                    except Exception:
                                                        pass
                                                    return len(v) <= 2
                                                return False
                                            try:
                                                _pg_no_local = int(p.get("page") or p.get("page_number") or -1)
                                            except Exception:
                                                _pg_no_local = None
                                            min_img_y2 = min(float(im.get("y", 0) or 0.0) for im in inline_imgs)
                                            candidate_texts2 = []
                                            for it in items:
                                                if it.get("type") != "text" or not it.get("bBox"):
                                                    continue
                                                val_txt = (it.get("value") or it.get("md") or "").strip()
                                                if _is_trivial_number(val_txt, _pg_no_local):
                                                    continue
                                                # Select texts that likely anchor images: token-overlap OR 'step' lines OR substantial width
                                                bb = it.get("bBox") or {}
                                                tw = float(bb.get("w", 0) or 0.0)
                                                is_step = ("step" in val_txt.lower())
                                                if (_overlap(q_all_tokens, val_txt) >= 1) or is_step or (tw >= 300.0):
                                                    candidate_texts2.append(it)
                                            candidate_texts2.sort(key=lambda t: (float((t.get("bBox") or {}).get("y", 0) or 0.0), float((t.get("bBox") or {}).get("x", 0) or 0.0)))
                                            ordered_imgs2 = sorted(inline_imgs, key=lambda im: (float(im.get("y", 0) or 0.0), float(im.get("x", 0) or 0.0)))

                                            # Heading-anchor override: if the best matching item is a heading
                                            # (e.g., "Step 8: Click on the open job icon"), select the first image
                                            # immediately below that heading.
                                            try:
                                                if best_item and (best_item.get("type") == "heading") and (best_overlap and best_overlap > 0):
                                                    hy = float((best_item.get("bBox") or {}).get("y", 0) or 0.0)
                                                    below_imgs = [im for im in ordered_imgs2 if float(im.get("y", 0) or 0.0) >= (hy + 1.0)]
                                                    if below_imgs:
                                                        candidate = below_imgs[0]
                                                        # Lock this pick by assigning a very high score so later ranking cannot override it
                                                        best_pick = (candidate, pn)
                                                        best_pick_score = 10001.0
                                                        # Stop further ranking; we've anchored to the heading
                                                        raise StopIteration
                                            except StopIteration:
                                                pass

                                            # Detect step number or ordinal in query for ordinal preference
                                            step_index = None
                                            try:
                                                m_step = _re4.search(r"\bstep\s*(\d+)\b", (query or ""), flags=_re4.IGNORECASE)
                                                if m_step:
                                                    step_val = int(m_step.group(1))
                                                    if step_val >= 1:
                                                        step_index = step_val - 1
                                            except Exception:
                                                step_index = None
                                            # Ordinal words (first/second/third...) mapping
                                            try:
                                                ord_map = {
                                                    "first": 0, "1st": 0, "one": 0,
                                                    "second": 1, "2nd": 1, "two": 1,
                                                    "third": 2, "3rd": 2, "three": 2,
                                                    "fourth": 3, "4th": 3, "four": 3,
                                                    "fifth": 4, "5th": 4, "five": 4,
                                                    "sixth": 5, "6th": 5, "six": 5,
                                                    "seventh": 6, "7th": 6, "seven": 6,
                                                    "eighth": 7, "8th": 7, "eight": 7,
                                                    "ninth": 8, "9th": 8, "nine": 8,
                                                    "tenth": 9, "10th": 9, "ten": 9,
                                                }
                                                ql = (query or "").strip().lower()
                                                for k, v in ord_map.items():
                                                    if k in ql:
                                                        step_index = v
                                                        break
                                            except Exception:
                                                pass

                                            # Best matching text for this query, with caption preference
                                            # Page-wide Figure[...] → image-index mapping (independent of caption detection)
                                            try:
                                                import re as _re_figp0
                                                def _extract_fig_lines_page0() -> List[tuple]:
                                                    lines_all = []
                                                    items_all = p.get("items") or []
                                                    for it2 in items_all:
                                                        if it2.get("type") != "text":
                                                            continue
                                                        tb = it2.get("bBox") or {}
                                                        y0 = float(tb.get("y", 0) or 0.0)
                                                        raw = (it2.get("value") or it2.get("md") or "")
                                                        parts = [ln.strip() for ln in raw.splitlines() if (ln or "").strip()]
                                                        j = 0
                                                        for ln in parts:
                                                            s = (ln or "").lower()
                                                            if _re_figp0.search(r"\bfig\s*\[[^\]]*\]", s):
                                                                lines_all.append((y0 + j*0.001, ln))
                                                            j += 1
                                                    lines_all.sort(key=lambda t: t[0])
                                                    return lines_all
                                                fig_lines_page0 = _extract_fig_lines_page0()
                                                if fig_lines_page0 and ordered_imgs2:
                                                    def _ovl_page0(line: str) -> int:
                                                        return _overlap(q_all_tokens, line)
                                                    best_line_idx0 = max(range(len(fig_lines_page0)), key=lambda i: (_ovl_page0(fig_lines_page0[i][1]), i))
                                                    if _ovl_page0(fig_lines_page0[best_line_idx0][1]) > 0:
                                                        ord_idx0 = max(0, min(best_line_idx0, len(ordered_imgs2)-1))
                                                        mapped0 = ordered_imgs2[ord_idx0]
                                                        nm0 = mapped0.get("name") or mapped0.get("filename")
                                                        if nm0:
                                                            best_pick = (mapped0, pn)
                                                            best_pick_score = 10002.0
                                                            raise StopIteration
                                            except StopIteration:
                                                pass
                                            except Exception:
                                                pass

                                            # Best matching text for this query, with caption preference
                                            def _val_txt(it):
                                                return (it.get("value") or it.get("md") or "")
                                            def _looks_like_caption_txt(txt: str) -> bool:
                                                s = (txt or "").strip().lower()
                                                if not s:
                                                    return False
                                                if s.startswith("fig") or "fig[" in s or "figure" in s:
                                                    return True
                                                if ":" in s and len(s) <= 160:
                                                    return True
                                                return len(s) <= 60
                                            best_text2 = None
                                            best_text_score2 = -1
                                            # First, try to anchor on a caption-like text that overlaps the query
                                            caps = []
                                            for it in candidate_texts2:
                                                tv = _val_txt(it)
                                                if _looks_like_caption_txt(tv):
                                                    sc = _overlap(q_all_tokens, tv)
                                                    caps.append((sc, float((it.get("bBox") or {}).get("y", 0) or 0.0), it))
                                            if caps:
                                                # Prefer higher overlap, then lower on page (greater y)
                                                caps.sort(key=lambda x: (x[0], x[1]))
                                                sc_cap, _, it_cap = caps[-1]
                                                if sc_cap > 0:
                                                    best_text2 = it_cap
                                                    best_text_score2 = sc_cap
                                            if best_text2 is None:
                                                for it in candidate_texts2:
                                                    sc = _overlap(q_all_tokens, _val_txt(it))
                                                    if sc > best_text_score2:
                                                        best_text_score2 = sc
                                                        best_text2 = it

                                            # Helper for anchor/ocr
                                            def _ocr_text(im: Dict) -> str:
                                                return " ".join((e.get("text") or "") for e in (im.get("ocr") or []))
                                            def _anchor_texts(im: Dict) -> List[str]:
                                                a = im.get("anchors") or {}
                                                return [
                                                    ((a.get("heading") or {}).get("text") or ""),
                                                    ((a.get("above_text") or {}).get("text") or ""),
                                                    ((a.get("below_text") or {}).get("text") or ""),
                                                ]

                        # If best-text found: proximity + phrase/token mapping (caption-aware). No keyword lists.
                                            if best_text2 and ordered_imgs2:
                                                try:
                            # 0) Removed semantic keyword preference. Proceed with layout-aware logic.
                                                    # 0a) Step-region mapping: if the page contains multiple step lines,
                                                    # map the current step text to the first image between this step and the next step.
                                                    try:
                                                        step_texts = []
                                                        for it2 in (p.get("items") or []):
                                                            if it2.get("type") == "text":
                                                                tv2 = (it2.get("value") or it2.get("md") or "")
                                                                if "step" in tv2.lower() and it2.get("bBox"):
                                                                    yv2 = float((it2.get("bBox") or {}).get("y", 0) or 0.0)
                                                                    step_texts.append((yv2, it2))
                                                        if len(step_texts) >= 2:
                                                            step_texts.sort(key=lambda t: t[0])
                                                            by = float((best_text2.get("bBox") or {}).get("y", 0) or 0.0)
                                                            # Find this step's index by nearest y
                                                            cur_idx = min(range(len(step_texts)), key=lambda i: abs(step_texts[i][0] - by))
                                                            lb = step_texts[cur_idx][0]
                                                            ub = step_texts[cur_idx+1][0] if cur_idx+1 < len(step_texts) else None
                                                            in_region = [im for im in ordered_imgs2 if float(im.get("y", 0) or 0.0) >= (lb + 1.0) and (ub is None or float(im.get("y", 0) or 0.0) < (ub - 1.0))]
                                                            if in_region:
                                                                # Prefer the lowest image in the step region (later action on the page)
                                                                mapped = sorted(in_region, key=lambda im: (float(im.get("y", 0) or 0.0), float(im.get("x", 0) or 0.0)))[-1]
                                                                nm_reg = mapped.get("name") or mapped.get("filename")
                                                                if nm_reg:
                                                                    best_pick = (mapped, pn)
                                                                    best_pick_score = 10000.0
                                                                    # Done with mapping for this step
                                                                    raise StopIteration
                                                    except StopIteration:
                                                        pass
                                                    except Exception:
                                                        pass
                                                    # Decide if best_text2 looks like a caption (e.g., "Fig ...: ..." or short label under an image)
                                                    tbb = best_text2.get("bBox") or {}
                                                    ty = float(tbb.get("y", 0) or 0.0)
                                                    _val_bt = (best_text2.get("value") or best_text2.get("md") or "")
                                                    def _looks_like_caption(txt: str) -> bool:
                                                        s = (txt or "").strip().lower()
                                                        if not s:
                                                            return False
                                                        if s.startswith("fig") or "fig[" in s or "figure" in s:
                                                            return True
                                                        if ":" in s and len(s) <= 160:
                                                            return True
                                                        # very short, likely label near image
                                                        return len(s) <= 60
                                                    is_caption = _looks_like_caption(_val_bt)

                                                    # 1) choose best image relative to the text
                                                    # If caption-like: try caption-index → image-index mapping first;
                                                    # then fallback to nearest-above; else: nearest below with combined score
                                                    above = [im for im in ordered_imgs2 if float(im.get("y", 0) or 0.0) <= (ty - 1.0)]
                                                    below = [im for im in ordered_imgs2 if float(im.get("y", 0) or 0.0) >= (ty + 1.0)]
                                                    mapped = None
                                                    if is_caption:
                                                        # 1a) Page-wide figure-lines → image-index mapping
                                                        try:
                                                            import re as _re_figp
                                                            def _extract_fig_lines_page() -> List[tuple]:
                                                                lines_all = []
                                                                items_all = p.get("items") or []
                                                                for it2 in items_all:
                                                                    if it2.get("type") != "text":
                                                                        continue
                                                                    tb = it2.get("bBox") or {}
                                                                    y0 = float(tb.get("y", 0) or 0.0)
                                                                    raw = (it2.get("value") or it2.get("md") or "")
                                                                    parts = [ln.strip() for ln in raw.splitlines() if (ln or "").strip()]
                                                                    j = 0
                                                                    for ln in parts:
                                                                        s = (ln or "").lower()
                                                                        if _re_figp.search(r"\bfig\s*\[[^\]]*\]", s):
                                                                            # add tiny offset to preserve within-block order
                                                                            lines_all.append((y0 + j*0.001, ln))
                                                                        j += 1
                                                                lines_all.sort(key=lambda t: t[0])
                                                                return lines_all
                                                            fig_lines_page = _extract_fig_lines_page()
                                                            if fig_lines_page:
                                                                def _ovl_page(line: str) -> int:
                                                                    return _overlap(q_all_tokens, line)
                                                                # pick the figure line with best overlap
                                                                best_line_idx = max(range(len(fig_lines_page)), key=lambda i: (_ovl_page(fig_lines_page[i][1]), i))
                                                                if _ovl_page(fig_lines_page[best_line_idx][1]) > 0:
                                                                    # Only map when counts match; else if a single caption likely covers multiple images, prefer last
                                                                    if len(fig_lines_page) == len(ordered_imgs2):
                                                                        ord_idx = max(0, min(best_line_idx, len(ordered_imgs2)-1))
                                                                        mapped = ordered_imgs2[ord_idx]
                                                                    elif len(fig_lines_page) == 1 and len(ordered_imgs2) > 1:
                                                                        mapped = ordered_imgs2[-1]
                                                        except Exception:
                                                            mapped = None
                                                        # 1a) If caption text contains multiple figure lines (e.g., Fig[4], Fig[4.1], Fig[5])
                                                        # map the matching line (by token overlap with query) to the same ordinal image index
                                                        try:
                                                            import re as _re_fig
                                                            lines = [ln.strip() for ln in (_val_bt or "").splitlines() if (ln or "").strip()]
                                                            def _is_fig_line(s: str) -> bool:
                                                                return bool(_re_fig.search(r"\bfig\s*\[[^\]]*\]", (s or "").lower()))
                                                            fig_lines = [(i, ln) for i, ln in enumerate(lines) if _is_fig_line(ln)]
                                                            if fig_lines:
                                                                # choose the figure line with best token overlap with query
                                                                def _ovl(line: str) -> int:
                                                                    return _overlap(q_all_tokens, line)
                                                                best_idx, best_line = max(fig_lines, key=lambda t: (_ovl(t[1]), t[0]))
                                                                if _ovl(best_line) > 0:
                                                                    ord_idx = min(best_idx, len(ordered_imgs2) - 1)
                                                                    mapped = ordered_imgs2[ord_idx]
                                                        except Exception:
                                                            mapped = None
                                                        # Try caption index mapping: map k-th caption (top→bottom) to k-th image (top→bottom)
                                                        try:
                                                            items_all = p.get("items") or []
                                                            caps_all = []
                                                            for it2 in items_all:
                                                                if it2.get("type") == "text":
                                                                    tv2 = (it2.get("value") or it2.get("md") or "")
                                                                    if _looks_like_caption(tv2):
                                                                        yv2 = float((it2.get("bBox") or {}).get("y", 0) or 0.0)
                                                                        caps_all.append((yv2, tv2, it2))
                                                            if caps_all:
                                                                caps_all.sort(key=lambda x: x[0])
                                                                # find index of best_text2 by closest y and same text
                                                                by = float((best_text2.get("bBox") or {}).get("y", 0) or 0.0)
                                                                btxt = (best_text2.get("value") or best_text2.get("md") or "")
                                                                # tolerance in Y to match identical caption line if duplicated
                                                                cap_idx = None
                                                                for i,(yv, tv, itv) in enumerate(caps_all):
                                                                    if abs(yv - by) <= 2.0 and (tv.strip() == btxt.strip() or not btxt.strip()):
                                                                        cap_idx = i; break
                                                                if cap_idx is None:
                                                                    # fallback: nearest by y
                                                                    cap_idx = min(range(len(caps_all)), key=lambda i: abs(caps_all[i][0] - by))
                                                                # Only map indices if counts line up; if single caption likely spans multiple images, prefer last
                                                                if len(caps_all) == len(ordered_imgs2):
                                                                    cap_idx = max(0, min(cap_idx, len(ordered_imgs2)-1))
                                                                    mapped = ordered_imgs2[cap_idx]
                                                                elif len(caps_all) == 1 and len(ordered_imgs2) > 1:
                                                                    mapped = ordered_imgs2[-1]
                                                        except Exception:
                                                            mapped = None
                                                    if mapped is None and is_caption and above:
                                                        # nearest image above (by vertical distance); light x proximity tie-breaker
                                                        def _score_above(im):
                                                            ib = _bbox(im)
                                                            ix = _center_x(ib); iy = _center_y(ib)
                                                            dx = abs(ix - _center_x(tbb)); dy = max(0.0, (ty - iy))
                                                            return dy + 0.25 * dx
                                                        mapped = min(above, key=_score_above)
                                                    elif below:
                                                        def _score_below2(im):
                                                            ib = _bbox(im)
                                                            ix = _center_x(ib); iy = _center_y(ib)
                                                            dx = abs(ix - _center_x(tbb)); dy = max(0.0, iy - _center_y(tbb))
                                                            prox = 1.0 / (1.0 + dy + 0.25 * dx)
                                                            bag_txt = " ".join(_anchor_texts(im) + [_ocr_text(im)])
                                                            hits = _overlap(q_all_tokens, bag_txt)
                                                            bag_norm = hits / max(1, len(q_all_tokens))
                                                            try:
                                                                bag_ns = _re4.sub(r"\s+", "", (bag_txt or "").lower())
                                                                phrase_boost = 0.5 if (q_phrase_norm and (q_phrase_norm in bag_ns)) or (len(q_full_norm) >= 10 and q_full_norm in bag_ns) else 0.0
                                                            except Exception:
                                                                phrase_boost = 0.0
                                                            bag_score = min(1.0, bag_norm + phrase_boost)
                                                            size_score = 0.0
                                                            if page_w and page_h:
                                                                area = float(im.get("width",0) or 0.0) * float(im.get("height",0) or 0.0)
                                                                page_area = page_w * page_h
                                                                if page_area > 0:
                                                                    ar = area / page_area
                                                                    wr = float(im.get("width",0) or 0.0) / page_w
                                                                    if ar < 0.01 or wr < 0.12:
                                                                        size_score -= 0.25
                                                                    else:
                                                                        size_score += min(0.15, ar * 0.6)
                                                                    # No domain keyword biases; use only bag/proximity/size and a light y-depth bias
                                                                    ybias = 0.0
                                                                    if page_h:
                                                                        y_ratio = min(1.0, max(0.0, iy / page_h))
                                                                        ybias = 0.05 * y_ratio
                                                                    return 0.6 * bag_score + 0.2 * prox + 0.15 * size_score + ybias
                                                        mapped = sorted(below, key=lambda im: -_score_below2(im))[0]
                                                    # 2) fallback: caption-lowest-above mapping if caption(s) exist
                                                    if mapped is None:
                                                        try:
                                                            caps_all = []
                                                            for it in candidate_texts2:
                                                                tv = (it.get("value") or it.get("md") or "")
                                                                if _looks_like_caption(tv):
                                                                    yv = float((it.get("bBox") or {}).get("y", 0) or 0.0)
                                                                    caps_all.append((yv, it))
                                                            if caps_all:
                                                                caps_all.sort(key=lambda x: x[0])
                                                                _, cap_it = caps_all[-1]  # lowest caption on page
                                                                cap_bb = cap_it.get("bBox") or {}
                                                                cy = float(cap_bb.get("y", 0) or 0.0)
                                                                above_cap = [im for im in ordered_imgs2 if float(im.get("y", 0) or 0.0) <= (cy - 1.0)]
                                                                if above_cap:
                                                                    # nearest above caption
                                                                    def _cap_above_score(im):
                                                                        ib = _bbox(im)
                                                                        return (cy - _center_y(ib)) + 0.25 * abs(_center_x(ib) - _center_x(cap_bb))
                                                                    mapped = min(above_cap, key=_cap_above_score)
                                                                else:
                                                                    # fallback to last image on page
                                                                    mapped = ordered_imgs2[-1]
                                                        except Exception:
                                                            pass
                                                    # 3) fallback: step-based or ordinal index map
                                                    if mapped is None:
                                                        try:
                                                            idx_text = next(i for i, t in enumerate(candidate_texts2) if t is best_text2)
                                                        except StopIteration:
                                                            idx_text = None
                                                        desired_idx = step_index if (step_index is not None) else idx_text
                                                        if desired_idx is not None:
                                                            desired_idx = max(0, min(desired_idx, len(ordered_imgs2) - 1))
                                                            mapped = ordered_imgs2[desired_idx]
                                                    if mapped is not None:
                                                        nm = mapped.get("name") or mapped.get("filename")
                                                        if nm:
                                                            sc = image_score(mapped)
                                                            if sc > best_pick_score:
                                                                best_pick = (mapped, pn)
                                                                best_pick_score = sc
                                                            raise StopIteration
                                                except StopIteration:
                                                    pass

                                            # Otherwise, rank by nearest text alignment + bag overlap + base score
                                            def _nearest_text_scores2(img: Dict):
                                                ib = _bbox(img)
                                                ix = _center_x(ib); iy = _center_y(ib)
                                                best_ab = None; best_bl = None; dab = 1e9; dbl = 1e9
                                                for it in (candidate_texts2 or []):
                                                    tb = it.get("bBox") or {}
                                                    tx = _center_x(tb); ty = _center_y(tb)
                                                    dx = abs(ix - tx); dy = iy - ty
                                                    horiz_overlap = not ((tb.get("x",0)+tb.get("w",0) < ib.get("x",0)) or (ib.get("x",0)+ib.get("w",0) < tb.get("x",0)))
                                                    penalty = 0.0 if horiz_overlap else min(200.0, dx)
                                                    if dy > 0:
                                                        d = dy + 0.3*penalty
                                                        if d < dab:
                                                            dab = d; best_ab = it
                                                    else:
                                                        d = (-dy) + 0.4*penalty
                                                        if d < dbl:
                                                            dbl = d; best_bl = it
                                                return best_ab, dab, best_bl, dbl

                                            def _final_score2(img: Dict) -> float:
                                                base = image_score(img)
                                                bag = " ".join(_anchor_texts(img) + [_ocr_text(img)])
                                                bag_hits = _overlap(q_all_tokens, bag)
                                                try:
                                                    bag_ns = _re4.sub(r"\s+", "", (bag or "").lower())
                                                    if (q_phrase_norm and q_phrase_norm in bag_ns) or (len(q_full_norm) >= 10 and q_full_norm in bag_ns):
                                                        return 10_000.0
                                                except Exception:
                                                    pass
                                                ab, dab, bl, dbl = _nearest_text_scores2(img)
                                                ab_hits = _overlap(q_all_tokens, (ab or {}).get("value") or (ab or {}).get("md") or "") if ab else 0
                                                bl_hits = _overlap(q_all_tokens, (bl or {}).get("value") or (bl or {}).get("md") or "") if bl else 0
                                                wa = 1.0 / (1.0 + max(5.0, dab)) if ab else 0.0
                                                wb = 1.0 / (1.0 + max(5.0, dbl)) if bl else 0.0
                                                text_score = wa*ab_hits + wb*bl_hits
                                                # Size guardrails
                                                size_bonus = 0.0
                                                if page_w and page_h:
                                                    area = float(img.get("width",0) or 0.0) * float(img.get("height",0) or 0.0)
                                                    page_area = page_w*page_h
                                                    if page_area > 0:
                                                        ar = area / page_area
                                                        wr = float(img.get("width",0) or 0.0) / page_w
                                                        if ar < 0.01 or wr < 0.12:
                                                            size_bonus -= 0.25
                                                        else:
                                                            size_bonus += min(0.15, ar*0.6)
                                                # Remove vertical-depth bias to avoid preferring later images on the page
                                                return 0.45*text_score + 0.30*bag_hits + 0.20*base + size_bonus

                                            # Rank primarily by score; break ties by earlier image index (1 before 2)
                                            ranked = sorted(inline_imgs, key=lambda im: (-_final_score2(im), _img_index(im)))
                                            # Prefer the highest-ranked image (no depth bias)
                                            candidate = ranked[0]
                                        except Exception:
                                            # Fallback: score, then earlier image index
                                            inline_imgs.sort(key=lambda im: (-image_score(im), _img_index(im)))
                                            candidate = inline_imgs[0]
                                        sc = image_score(candidate)
                                        if sc > best_pick_score:
                                            best_pick = (candidate, pn)
                                            best_pick_score = sc
                                    # Removed unconditional deepest-image preference to avoid picking the last image when earlier is correct
                                    # If no inline images exist on the target page, fallback to page screenshot to keep same-page guarantee
                                    if (not inline_imgs) and (pn in candidate_pages) and chosen_image is None:
                                        try:
                                            from pathlib import Path as _P
                                            fname_cur = (data.get("metadata", {}) or {}).get("file_name", target_file)
                                            prefix_cur = _derive_image_prefix(fname_cur)
                                            shot_pref = _P(config.OUTPUT_DIRECTORY) / "images" / f"{prefix_cur}_page_{pn}.jpg"
                                            shot_gen = _P(config.OUTPUT_DIRECTORY) / "images" / f"page_{pn}.jpg"
                                            shot = shot_pref if shot_pref.exists() else shot_gen
                                            if shot.exists():
                                                name = shot.name
                                                chosen_image = {
                                                    "filename": name,
                                                    "url": f"/output/images/{name}",
                                                    "score": 1.0,
                                                    "model_used": "page-screenshot",
                                                    "detailed_description": "",
                                                    "confidence": "high",
                                                    "priority": "primary",
                                                    "page_number": pn,
                                                    "page_rank": 2
                                                }
                                                # Stop after selecting screenshot
                                                break
                                        except Exception:
                                            pass
                        if best_pick:
                            pick, pn = best_pick
                            name = pick.get("name") or pick.get("filename")
                            if name:
                                chosen_image = {
                                    "filename": name,
                                    "url": f"/output/images/{name}",
                                    "score": 1.0,
                                    "model_used": "page-link",
                                    "detailed_description": "",
                                    "confidence": "high",
                                    "priority": "primary",
                                    "page_number": pn,
                                    "page_rank": 2
                                }
                    except Exception as e:
                        print(f"[Image-Select-Fallback-ERROR] {e}")

            images = [chosen_image] if chosen_image else []

            # Final exact-heading override: if the query exactly matches a heading on another page,
            # force selection from that page (inline image if present else page screenshot).
            try:
                if target_file and (query or "").strip():
                    from pathlib import Path as _P
                    json_candidates = [
                        config.OUTPUT_DIRECTORY / target_file,
                        (_P(config.BASE_DIR).parent / "output" / target_file),
                    ]
                    def _norm_head(s: str) -> str:
                        import re as _re
                        s = s or ""
                        s = _re.sub(r"^\s*#+\s*", "", s)
                        s = _re.sub(r"^\s*\d+\s*[\.):-]?\s*", "", s)
                        return _re.sub(r"[^A-Za-z0-9]+", " ", s).strip().lower()
                    qh = _norm_head(query)
                    heading_page = None
                    for json_path in json_candidates:
                        if not json_path.exists():
                            continue
                        data = _safe_json_load(json_path) or {}
                        for p in (data.get("pages") or []):
                            try:
                                pn = int(p.get("page") or p.get("page_number") or -1)
                            except Exception:
                                pn = -1
                            if pn <= 0:
                                continue
                            for it in (p.get("items") or []):
                                if it.get("type") == "heading":
                                    hv = (it.get("value") or it.get("md") or "")
                                    if _norm_head(hv) == qh and qh:
                                        heading_page = pn
                                        break
                            if heading_page:
                                break
                        if heading_page:
                            break
                    if heading_page and (not images or images[0].get("page_number") != heading_page):
                        chosen_image2 = None
                        for json_path in json_candidates:
                            if not json_path.exists():
                                continue
                            data = _safe_json_load(json_path) or {}
                            for p in (data.get("pages") or []):
                                try:
                                    pn = int(p.get("page") or p.get("page_number") or -1)
                                except Exception:
                                    pn = -1
                                if pn != heading_page:
                                    continue
                                imgs = p.get("images", [])
                                inline_imgs = [i for i in imgs if (i.get("type") or i.get("img_type")) != "full_page_screenshot"]
                                if inline_imgs:
                                    # Find the heading item on this page to anchor selection
                                    by = None
                                    items2 = p.get("items") or []
                                    for it in items2:
                                        if it.get("type") == "heading":
                                            hv = (it.get("value") or it.get("md") or "")
                                            if _norm_head(hv) == qh and it.get("bBox"):
                                                by = float((it.get("bBox") or {}).get("y", 0) or 0.0)
                                                break
                                    page_w = float(p.get("width") or 0.0)
                                    page_h = float(p.get("height") or 0.0)
                                    # Filter to images below heading and ignore tiny icons
                                    cand = []
                                    for im in inline_imgs:
                                        iy = float(im.get("y", 0) or 0.0)
                                        if by is not None and iy < (by + 10):
                                            continue
                                        w = float(im.get("width", 0) or 0.0)
                                        h = float(im.get("height", 0) or 0.0)
                                        area = w * h
                                        area_ratio = (area / (page_w * page_h)) if (page_w and page_h) else 0.0
                                        width_ratio = (w / page_w) if page_w else 0.0
                                        if area_ratio < 0.05 or width_ratio < 0.25:
                                            continue
                                        cand.append(im)
                                    pool = cand if cand else inline_imgs  # fallback to all if filter removes all
                                    def _prox(im):
                                        iy = float(im.get("y", 0) or 0.0)
                                        return 1.0 / (1.0 + max(0.0, (iy - (by or 0.0))))
                                    scored = []
                                    for im in pool:
                                        w = float(im.get("width", 0) or 0.0)
                                        h = float(im.get("height", 0) or 0.0)
                                        area = w * h
                                        area_ratio = (area / (page_w * page_h)) if (page_w and page_h) else 0.0
                                        width_ratio = (w / page_w) if page_w else 0.0
                                        sc = 0.55 * area_ratio + 0.30 * _prox(im) + 0.15 * width_ratio
                                        scored.append((sc, im))
                                    scored.sort(key=lambda x: x[0], reverse=True)
                                    pick = scored[0][1]
                                    name = pick.get("name") or pick.get("filename")
                                    if name:
                                        chosen_image2 = {
                                            "filename": name,
                                            "url": f"/output/images/{name}",
                                            "score": 1.0,
                                            "model_used": "heading-lock",
                                            "detailed_description": "",
                                            "confidence": "high",
                                            "priority": "primary",
                                            "page_number": pn,
                                            "page_rank": 2
                                        }
                                    else:
                                        # fallback to page screenshot
                                        from pathlib import Path as _P
                                        fname_cur = (data.get("metadata", {}) or {}).get("file_name", target_file)
                                        prefix_cur = _derive_image_prefix(fname_cur)
                                        shot_pref = (_P(config.OUTPUT_DIRECTORY) / "images" / f"{prefix_cur}_page_{pn}.jpg")
                                        shot = shot_pref if shot_pref.exists() else (_P(config.OUTPUT_DIRECTORY) / "images" / f"page_{pn}.jpg")
                                        if shot.exists():
                                            sname = shot.name
                                            chosen_image2 = {
                                                "filename": sname,
                                                "url": f"/output/images/{sname}",
                                                "score": 1.0,
                                                "model_used": "heading-screenshot",
                                                "detailed_description": "",
                                                "confidence": "high",
                                                "priority": "primary",
                                                "page_number": pn,
                                                "page_rank": 2
                                            }
                                    break
                            if chosen_image2:
                                break
                        if chosen_image2:
                            images = [chosen_image2]
            except Exception:
                pass

        if is_visual and PAGE_LINK_IMAGES_ONLY:
            # Visual queries: same-page-only image selection using layout-aware ranking
            target_file = best_node_file or primary_file
            target_page = best_node_page or (primary_pages[0] if primary_pages else None)
            chosen_image = None
            if target_file and target_page is not None:
                candidate_pages = [int(target_page)]
                candidate_pages = [p for p in sorted(set(candidate_pages)) if p > 0]
                try:
                    from pathlib import Path as _Path
                    import re as _re5
                    json_candidates = [
                        config.OUTPUT_DIRECTORY / target_file,
                        (_Path(config.BASE_DIR).parent / "output" / target_file),
                    ]
                    def _bbox2(obj):
                        b = obj.get("bBox") or {}
                        return {
                            "x": float(b.get("x", obj.get("x", 0.0)) or 0.0),
                            "y": float(b.get("y", obj.get("y", 0.0)) or 0.0),
                            "w": float(b.get("w", obj.get("width", 0.0)) or 0.0),
                            "h": float(b.get("h", obj.get("height", 0.0)) or 0.0),
                        }
                    def _cx(b): return b["x"] + b["w"]/2.0
                    def _cy(b): return b["y"] + b["h"]/2.0
                    def _is_inline2(im):
                        t = (im.get("type") or im.get("img_type") or "").lower()
                        return t != "full_page_screenshot"
                    def _tokens2(s: str):
                        return _re5.findall(r"[a-z0-9]+", (s or "").lower())
                    def _overlap2(qt, text):
                        st = set(_tokens2(text))
                        return sum(1 for t in qt if t in st)
                    q2 = (query or "")
                    q2_tokens = _tokens2(q2)
                    for json_path in json_candidates:
                        if not json_path.exists():
                            continue
                        data = _safe_json_load(json_path) or {}
                        for p in (data.get("pages") or []):
                            try:
                                pn = int(p.get("page") or p.get("page_number") or -1)
                            except Exception:
                                pn = -1
                            if pn not in candidate_pages:
                                continue
                            imgs = [im for im in (p.get("images") or []) if _is_inline2(im)]
                            if not imgs:
                                # strict same-page fallback to screenshot
                                try:
                                    from pathlib import Path as _P
                                    fname_cur = (data.get("metadata", {}) or {}).get("file_name", target_file)
                                    prefix_cur = _derive_image_prefix(fname_cur)
                                    shot_pref = _P(config.OUTPUT_DIRECTORY) / "images" / f"{prefix_cur}_page_{pn}.jpg"
                                    shot = shot_pref if shot_pref.exists() else (_P(config.OUTPUT_DIRECTORY) / "images" / f"page_{pn}.jpg")
                                    if shot.exists():
                                        name = shot.name
                                        chosen_image = {
                                            "filename": name,
                                            "url": f"/output/images/{name}",
                                            "score": 1.0,
                                            "model_used": "page-screenshot",
                                            "detailed_description": "",
                                            "confidence": "high",
                                            "priority": "primary",
                                            "page_number": pn,
                                            "page_rank": 2
                                        }
                                except Exception:
                                    pass
                                break
                            # Order by Y
                            imgs_sorted = sorted(imgs, key=lambda im: (float(im.get("y",0) or 0.0), float(im.get("x",0) or 0.0)))
                            texts = [it for it in (p.get("items") or []) if it.get("type") == "text"]
                            # Candidate texts: with token overlap OR substantial width OR explicit step lines
                            cand_texts = []
                            for it in texts:
                                bb = it.get("bBox") or {}
                                tw = float(bb.get("w", 0) or 0.0)
                                tv = (it.get("value") or it.get("md") or "").strip()
                                if not tv:
                                    continue
                                if _re5.fullmatch(r"[0-9]+", tv):
                                    continue
                                if _overlap2(q2_tokens, tv) >= 1 or ("step" in tv.lower()) or (tw >= 300.0):
                                    cand_texts.append(it)
                            cand_texts.sort(key=lambda t: (float((t.get("bBox") or {}).get("y",0) or 0.0), float((t.get("bBox") or {}).get("x",0) or 0.0)))
                            # Page-wide Figure[...] → image-index mapping (independent of caption detection)
                            try:
                                import re as _re_figp0b
                                def _extract_fig_lines_page0b() -> List[tuple]:
                                    lines_all = []
                                    items_all = p.get("items") or []
                                    for it2 in items_all:
                                        if it2.get("type") != "text":
                                            continue
                                        tb = it2.get("bBox") or {}
                                        y0 = float(tb.get("y", 0) or 0.0)
                                        raw = (it2.get("value") or it2.get("md") or "")
                                        parts = [ln.strip() for ln in raw.splitlines() if (ln or "").strip()]
                                        j = 0
                                        for ln in parts:
                                            s = (ln or "").lower()
                                            if _re_figp0b.search(r"\bfig\s*\[[^\]]*\]", s):
                                                lines_all.append((y0 + j*0.001, ln))
                                            j += 1
                                    lines_all.sort(key=lambda t: t[0])
                                    return lines_all
                                fig_lines_page0b = _extract_fig_lines_page0b()
                                if fig_lines_page0b and imgs_sorted:
                                    def _ovl_page0b(line: str) -> int:
                                        return _overlap2(q2_tokens, line)
                                    best_line_idx0b = max(range(len(fig_lines_page0b)), key=lambda i: (_ovl_page0b(fig_lines_page0b[i][1]), i))
                                    if _ovl_page0b(fig_lines_page0b[best_line_idx0b][1]) > 0:
                                        ord_idx0b = max(0, min(best_line_idx0b, len(imgs_sorted)-1))
                                        mapped = imgs_sorted[ord_idx0b]
                            except Exception:
                                pass
                            # Best matching text (prefer caption-like if overlapping)
                            def _val_txt2(it):
                                return (it.get("value") or it.get("md") or "")
                            def _looks_like_caption_txt2(txt: str) -> bool:
                                s = (txt or "").strip().lower()
                                if not s: return False
                                if s.startswith("fig") or "fig[" in s or "figure" in s: return True
                                if ":" in s and len(s) <= 160: return True
                                return len(s) <= 60
                            best_t = None
                            best_ts = -1
                            caps2 = []
                            for it in cand_texts:
                                tv = _val_txt2(it)
                                if _looks_like_caption_txt2(tv):
                                    sc = _overlap2(q2_tokens, tv)
                                    caps2.append((sc, float((it.get("bBox") or {}).get("y",0) or 0.0), it))
                            if caps2:
                                caps2.sort(key=lambda x: (x[0], x[1]))
                                sc_cap2, _, it_cap2 = caps2[-1]
                                if sc_cap2 > 0:
                                    best_t = it_cap2
                                    best_ts = sc_cap2
                            if best_t is None:
                                for it in cand_texts:
                                    sc = _overlap2(q2_tokens, _val_txt2(it))
                                    if sc > best_ts:
                                        best_ts = sc; best_t = it
                            # If we have a good best text, semantic preference then proximity; caption => caption-index map then nearest above
                            mapped = None
                            if best_t is not None and cand_texts:
                                tbb = _bbox2(best_t)
                                ty = _cy(tbb)
                                tv = (best_t.get("value") or best_t.get("md") or "")
                                # 0) Removed semantic keyword preference. Proceed with caption/ordinal/proximity logic.
                                def _looks_like_caption2(txt: str) -> bool:
                                    s = (txt or "").strip().lower()
                                    if not s:
                                        return False
                                    if s.startswith("fig") or "fig[" in s or "figure" in s:
                                        return True
                                    if ":" in s and len(s) <= 160:
                                        return True
                                    return len(s) <= 60
                                is_caption2 = _looks_like_caption2(tv)
                                above = [im for im in imgs_sorted if (_cy(_bbox2(im)) <= ty - 1.0)]
                                below = [im for im in imgs_sorted if (_cy(_bbox2(im)) >= ty + 1.0)]
                                if is_caption2:
                                    # Page-wide figure-lines → image-index mapping (visual path)
                                    try:
                                        import re as _re_figp2
                                        def _extract_fig_lines_page2() -> List[tuple]:
                                            lines_all = []
                                            items_all = p.get("items") or []
                                            for it2 in items_all:
                                                if it2.get("type") != "text":
                                                    continue
                                                tb = it2.get("bBox") or {}
                                                y0 = float(tb.get("y", 0) or 0.0)
                                                raw = (it2.get("value") or it2.get("md") or "")
                                                parts = [ln.strip() for ln in raw.splitlines() if (ln or "").strip()]
                                                j = 0
                                                for ln in parts:
                                                    s = (ln or "").lower()
                                                    if _re_figp2.search(r"\bfig\s*\[[^\]]*\]", s):
                                                        lines_all.append((y0 + j*0.001, ln))
                                                    j += 1
                                            lines_all.sort(key=lambda t: t[0])
                                            return lines_all
                                        fig_lines_page2 = _extract_fig_lines_page2()
                                        if fig_lines_page2:
                                            def _ovl_page2(line: str) -> int:
                                                return _overlap2(q2_tokens, line)
                                            best_line_idx2 = max(range(len(fig_lines_page2)), key=lambda i: (_ovl_page2(fig_lines_page2[i][1]), i))
                                            if _ovl_page2(fig_lines_page2[best_line_idx2][1]) > 0:
                                                ord_idx2 = max(0, min(best_line_idx2, len(imgs_sorted)-1))
                                                mapped = imgs_sorted[ord_idx2]
                                    except Exception:
                                        mapped = None
                                    # 1a) Within-caption multiple figure lines mapping
                                    try:
                                        import re as _re_fig2
                                        lines = [ln.strip() for ln in (tv or "").splitlines() if (ln or "").strip()]
                                        def _is_fig_line2(s: str) -> bool:
                                            return bool(_re_fig2.search(r"\bfig\s*\[[^\]]*\]", (s or "").lower()))
                                        fig_lines2 = [(i, ln) for i, ln in enumerate(lines) if _is_fig_line2(ln)]
                                        if fig_lines2:
                                            def _ovl2(line: str) -> int:
                                                return _overlap2(q2_tokens, line)
                                            best_i2, best_line2 = max(fig_lines2, key=lambda t: (_ovl2(t[1]), t[0]))
                                            if _ovl2(best_line2) > 0:
                                                ord_idx2 = min(best_i2, len(imgs_sorted) - 1)
                                                mapped = imgs_sorted[ord_idx2]
                                    except Exception:
                                        mapped = None
                                    # caption index → image index mapping first
                                    try:
                                        items_all = p.get("items") or []
                                        caps_all = []
                                        for it2 in items_all:
                                            if it2.get("type") == "text":
                                                tv2 = (it2.get("value") or it2.get("md") or "")
                                                if _looks_like_caption_txt2(tv2):
                                                    yv2 = float((it2.get("bBox") or {}).get("y",0) or 0.0)
                                                    caps_all.append((yv2, tv2, it2))
                                        if caps_all:
                                            caps_all.sort(key=lambda x: x[0])
                                            by = _cy(tbb)
                                            btxt = tv
                                            cap_idx = None
                                            for i,(yv, tvv, itv) in enumerate(caps_all):
                                                if abs(yv - (by - (tbb["h"]/2.0))) <= 2.0 and (tvv.strip() == btxt.strip() or not btxt.strip()):
                                                    cap_idx = i; break
                                            if cap_idx is None:
                                                cap_idx = min(range(len(caps_all)), key=lambda i: abs(caps_all[i][0] - (by - (tbb["h"]/2.0))))
                                            cap_idx = max(0, min(cap_idx, len(imgs_sorted)-1))
                                            mapped = imgs_sorted[cap_idx]
                                    except Exception:
                                        mapped = None
                                if mapped is None and is_caption2 and above:
                                    mapped = min(above, key=lambda im: (ty - _cy(_bbox2(im))) + 0.25*abs(_cx(_bbox2(im)) - _cx(tbb)))
                                elif below:
                                    mapped = min(below, key=lambda im: _cy(_bbox2(im)) - ty)
                                # caption fallback: if no mapped yet, map from lowest caption
                                if mapped is None:
                                    try:
                                        caps_all2 = []
                                        for it in cand_texts:
                                            tv = _val_txt2(it)
                                            if _looks_like_caption_txt2(tv):
                                                yv = float((it.get("bBox") or {}).get("y",0) or 0.0)
                                                caps_all2.append((yv, it))
                                        if caps_all2:
                                            caps_all2.sort(key=lambda x: x[0])
                                            _, cap2 = caps_all2[-1]
                                            capb = _bbox2(cap2)
                                            cy2 = _cy(capb)
                                            above2 = [im for im in imgs_sorted if (_cy(_bbox2(im)) <= cy2 - 1.0)]
                                            if above2:
                                                mapped = min(above2, key=lambda im: (cy2 - _cy(_bbox2(im))) + 0.25*abs(_cx(_bbox2(im)) - _cx(capb)))
                                            else:
                                                mapped = imgs_sorted[-1]
                                    except Exception:
                                        pass
                                # fallback to ordinal only if we have positive overlap
                                if mapped is None and best_ts > 0:
                                    try:
                                        idx_text = next(i for i,t in enumerate(cand_texts) if t is best_t)
                                    except StopIteration:
                                        idx_text = None
                                    if idx_text is None:
                                        by = ty
                                        idx_text = sorted(((abs(_cy(_bbox2(t))-by), i) for i,t in enumerate(cand_texts)))[0][1] if cand_texts else None
                                    if idx_text is not None:
                                        idx_text = max(0, min(idx_text, len(imgs_sorted)-1))
                                        mapped = imgs_sorted[idx_text]
                            def final_score(im):
                                # Anchors + OCR as bag
                                ocr_txt = " ".join((e.get("text") or "") for e in (im.get("ocr") or []))
                                bag_txt = " ".join([
                                    ((im.get("anchors") or {}).get("heading") or {}).get("text") or "",
                                    ((im.get("anchors") or {}).get("above_text") or {}).get("text") or "",
                                    ((im.get("anchors") or {}).get("below_text") or {}).get("text") or "",
                                    ocr_txt,
                                ])
                                bag_hits = _overlap2(q2_tokens, bag_txt)
                                ib = _bbox2(im)
                                ix, iy = _cx(ib), _cy(ib)
                                # nearest text above/below among cand_texts
                                dab = 1e9; dbl = 1e9; above_hits=0; below_hits=0
                                for it in cand_texts:
                                    tb = _bbox2(it)
                                    tx, ty = _cx(tb), _cy(tb)
                                    dx = abs(ix-tx); dy = iy-ty
                                    horiz_overlap = not ((tb["x"]+tb["w"] < ib["x"]) or (ib["x"]+ib["w"] < tb["x"]))
                                    penalty = 0.0 if horiz_overlap else min(200.0, dx)
                                    d = abs(dy) + (0.3 if dy>0 else 0.4)*penalty
                                    sc = _overlap2(q2_tokens, (it.get("value") or it.get("md") or ""))
                                    if dy>0: # text above image
                                        if d<dab:
                                            dab=d; above_hits=sc
                                    else:
                                        if d<dbl:
                                            dbl=d; below_hits=sc
                                wa = 1.0/(1.0+max(5.0,dab)) if dab<1e9 else 0.0
                                wb = 1.0/(1.0+max(5.0,dbl)) if dbl<1e9 else 0.0
                                text_score = wa*above_hits + wb*below_hits
                                # small size guardrails
                                pw = float(p.get("width") or 0.0)
                                ph = float(p.get("height") or 0.0)
                                size_bonus = 0.0
                                if pw and ph:
                                    area = float(im.get("width",0) or 0.0) * float(im.get("height",0) or 0.0)
                                    pr = (area/(pw*ph)) if (pw and ph) else 0.0
                                    wr = float(im.get("width",0) or 0.0)/pw if pw else 0.0
                                    if pr < 0.01 or wr < 0.12:
                                        size_bonus -= 0.25
                                    else:
                                        size_bonus += min(0.15, pr*0.6)
                                return 0.5*text_score + 0.3*bag_hits + size_bonus
                            # If mapping by best-below succeeded, use it; else rank all
                            pick = mapped or sorted(imgs_sorted, key=lambda im: (-final_score(im), float(im.get("y",0) or 0.0)))[0]
                            name = pick.get("name") or pick.get("filename")
                            if name:
                                chosen_image = {
                                    "filename": name,
                                    "url": f"/output/images/{name}",
                                    "score": 1.0,
                                    "model_used": "page-link",
                                    "detailed_description": "",
                                    "confidence": "high",
                                    "priority": "primary",
                                    "page_number": pn,
                                    "page_rank": 2
                                }
                            break
                        if chosen_image:
                            break
                except Exception:
                    pass
            images = [chosen_image] if chosen_image else []

        # Final LLM call if deferred
        if llm_response is None:
            final_text = retrieved_text.strip()
            if final_text:
                llm_response = await _llm_call(final_text, query)
            else:
                llm_response = "The answer is not available in the provided context."

        return {
            "answer": llm_response,
            "images": images,
            "query_type": "visual" if is_visual else "text",
            "context_sources": {
                "text_available": bool(retrieved_text.strip()),
                "images_found": len(images),
                "primary_file": primary_file,
                "secondary_files": secondary_files
            }
        } 

    except Exception as e:
        print(f"[Retrieval-ERROR] {e}")
        return {"error": str(e)}



async def get_admin_indexes_from_db(db: AsyncSession) -> List[str]:
    """
    Return a list of Pinecone index names (cleaned) that correspond to
    admin_name values in the Admin table *and* actually exist in Pinecone.
    """
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    existing = set(pc.list_indexes().names())

    res = await db.execute(select(Admin.admin_name))
    admin_names = [row[0] for row in res.all()]

    out: List[str] = []
    for name in admin_names:
        cleaned = _clean_name(name)
        if cleaned in existing:
            out.append(cleaned)
    return out


async def _retrieval_single_index(
    query: str,
    index_name_clean: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Run similarity search in a *single* Pinecone index and return scored hits.
    Each hit: {index_name, text, score, metadata}.
    Now includes CLIP-based image search from the unified index.
    """
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    pinecone_index = pc.Index(index_name_clean)
    vector_store = PineconeVectorStore(pinecone_index=pinecone_index)

    embed_model = _get_embed_model()
    service_context = ServiceContext.from_defaults(llm=None, embed_model=embed_model)
    index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
    retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)

    nodes = await asyncio.to_thread(retriever.retrieve, query)
    out: List[Dict[str, Any]] = []
 
    for n in nodes:
        out.append(
            {
                "index_name": index_name_clean,
                "text": n.node.text,
                "score": getattr(n, "score", None),
                "metadata": n.node.metadata or {},
            }
        )
    
   
    try:
        from app.vector_db.upsert_image import search_images
        clip_images = await search_images(query, index_name_clean, top_k=3, model_type="clip")
        
       
        for img in clip_images:
            out.append(
                {
                    "index_name": index_name_clean,
                    "text": "", 
                    "score": img.get("score"),
                    "metadata": {
                        "type": "image",
                        "source_file": img.get("source_file"),
                        "url": img.get("url"),
                        "filename": img.get("filename"),
                    },
                }
            )
    except Exception as e:
        print(f"[CLIP-Search-ERROR in _retrieval_single_index] {e}")
    
    return out


async def retrieval_all_admins(
    query: str,
    db: AsyncSession,
    top_k_per_index: int = 3,
    top_k_final: int = 8,
) -> Any:
    """
    Enhanced multi-admin retrieval with automatic image search.
    Query ALL admin Pinecone indexes, merge best results, and include relevant images.
    """
    index_names = await get_admin_indexes_from_db(db)
    if not index_names:
        return {"error": "No admin document indexes are available."}

    is_visual = _is_visual_query(query)
    
    all_hits: List[Dict[str, Any]] = []
    all_admin_images: List[Dict[str, Any]] = []
    
    for ix in index_names:
        try:
            hits = await _retrieval_single_index(query, ix, top_k=top_k_per_index)
            all_hits.extend(hits)
            
            try:
                from app.vector_db.upsert_image import search_images
                image_top_k = 3 if is_visual else 2  # More images for visual queries
                admin_images = await search_images(query, ix, top_k=image_top_k, model_type="clip")
                
                for img in admin_images:
                    img["admin_index"] = ix  # Track which admin index this came from
                    all_admin_images.append(img)
                    
            except Exception as e:
                print(f"[MultiRetrieval] error searching images in index {ix}: {e}")
                
        except Exception as e:
            print(f"[MultiRetrieval] error querying index {ix}: {e}")

    if not all_hits and not all_admin_images:
        return "The answer is not available in the provided context."

    def _score(h: Dict[str, Any]) -> float:
        s = h.get("score")
        try:
            return float(s) if s is not None else -1e9
        except Exception:
            return -1e9

    all_hits.sort(key=_score, reverse=True)
    top_hits = all_hits[:top_k_final]

    context_lines = []
    relevant_files = set()
    file_scores = {}

    for h in top_hits:
        src_index = h["index_name"]
        meta = h.get("metadata", {})
        fname = meta.get("file_name") or meta.get("heading") or "unknown_source"
        snippet = (h["text"] or "").strip()
        
        if snippet and meta.get("type") != "image":
            context_lines.append(f"[{src_index} :: {fname}]\n{snippet}")
            relevant_files.add(fname)
            
            score = h.get("score", 0)
            if fname not in file_scores or score > file_scores[fname]:
                file_scores[fname] = score

    primary_file = None
    secondary_files = []
    if file_scores:
        sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
        primary_file = sorted_files[0][0]
        primary_score = sorted_files[0][1]
        
        for fname, score in sorted_files[1:]:
            if abs(primary_score - score) < 0.015:
                secondary_files.append(fname)

    # If no text-based primary_file was identified, derive it from image hits to keep image/file consistent
    if not primary_file and all_admin_images:
        try:
            # Score by exact JSON source_file with max score
            by_src: Dict[str, float] = {}
            for img in all_admin_images:
                src = img.get("source_file") or ""
                sc = float(img.get("score") or 0.0)
                if src:
                    by_src[src] = max(sc, by_src.get(src, -1e9))
            if by_src:
                primary_file = max(by_src.items(), key=lambda t: t[1])[0]
        except Exception:
            pass

    filtered_images = []
    for img in all_admin_images:
        img_source_file = img.get("source_file") or ""
        if not img_source_file:
            continue
        base_file = img_source_file.split("_page")[0] if "_page" in img_source_file else img_source_file.split(".")[0]

        # If primary_file was derived from images, lock strictly to that file
        if primary_file and (primary_file.endswith(".json") or "." in primary_file):
            pf_base = primary_file.split("_page")[0] if "_page" in primary_file else primary_file.split(".")[0]
            if not (pf_base in base_file or base_file in pf_base):
                continue

        if is_visual:
            is_relevant = (primary_file and (base_file in primary_file or primary_file in base_file)) or \
                         any(base_file in sf or sf in base_file for sf in secondary_files) or \
                         not relevant_files  # If no text context, include best image matches
            if is_relevant:
                filtered_images.append(img)
        else:
            is_from_primary = primary_file and (base_file in primary_file or primary_file in base_file)
            is_from_secondary = any(base_file in sf or sf in base_file for sf in secondary_files)
            
            if is_from_primary or is_from_secondary:
                filtered_images.append(img)

    filtered_images.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Page inference and hydration on the primary file to avoid TOC drift
    page_text = ""
    target_page: Optional[int] = None
    if primary_file:
        try:
            import re as _re5
            from pathlib import Path as _P
            # Resolve JSON filename for the primary file (handles cases where metadata isn't a .json)
            json_name = primary_file
            if not (isinstance(json_name, str) and json_name.endswith('.json')):
                # Try to infer from images' source_file
                try:
                    base_pf = primary_file
                    base_pf = base_pf.split('_page')[0] if '_page' in base_pf else base_pf
                    base_pf_simple = base_pf.split('.')[0]
                    for _im in filtered_images or []:
                        srcf = _im.get('source_file') or ''
                        if not srcf:
                            continue
                        sbase = srcf.split('_page')[0] if '_page' in srcf else srcf
                        sbase_simple = sbase.split('.')[0]
                        if (base_pf in sbase) or (sbase in base_pf) or (base_pf_simple in sbase_simple) or (sbase_simple in base_pf_simple):
                            json_name = srcf
                            break
                except Exception:
                    pass
                # Fallback to appending .json
                if not (isinstance(json_name, str) and json_name.endswith('.json')):
                    json_name = f"{primary_file}.json"
            def _tokens2(s: str):
                return _re5.findall(r"[a-z0-9]+", (s or "").lower())
            def _overlap2(qt, text: str) -> int:
                st = set(_tokens2(text))
                return sum(1 for t in qt if t in st)
            def _norm_ns(s: str) -> str:
                return _re5.sub(r"\s+", "", (s or "").lower())
            def _json_best_page_for_query(file_name: str, q: str) -> Optional[int]:
                q = (q or "").strip()
                if not q:
                    return None
                qt = _tokens2(q)
                q_ns = _norm_ns(q)
                json_candidates = [
                    config.OUTPUT_DIRECTORY / file_name,
                    (_P(config.BASE_DIR).parent / "output" / file_name),
                ]
                exact_matches: List[int] = []
                best = None; best_sc = -1.0
                for jp in json_candidates:
                    if not jp.exists():
                        continue
                    data = _safe_json_load(jp) or {}
                    for p in (data.get("pages") or []):
                        try:
                            pn = int(p.get("page") or p.get("page_number") or -1)
                        except Exception:
                            pn = -1
                        if pn <= 0:
                            continue
                        items2 = p.get("items") or []
                        page_text_chunks = []
                        headings: List[str] = []
                        table_cells = 0
                        if p.get("text"):
                            page_text_chunks.append(p.get("text") or "")
                        if p.get("md"):
                            page_text_chunks.append(p.get("md") or "")
                        for it in items2:
                            t = (it.get("type") or it.get("item_type") or "").lower()
                            if t in ("text", "heading"):
                                val_txt = (it.get("value") or it.get("md") or "")
                                page_text_chunks.append(val_txt)
                                if t == "heading":
                                    headings.append(val_txt)
                            elif t == "table":
                                rows = it.get("rows") or []
                                try:
                                    for r in rows:
                                        table_cells += len(r)
                                except Exception:
                                    pass
                        for im in (p.get("images") or []):
                            a = im.get("anchors") or {}
                            page_text_chunks.append(((a.get("heading") or {}).get("text") or ""))
                            page_text_chunks.append(((a.get("above_text") or {}).get("text") or ""))
                            page_text_chunks.append(((a.get("below_text") or {}).get("text") or ""))
                            for e in (im.get("ocr") or []):
                                page_text_chunks.append(e.get("text") or "")
                        bag = " \n ".join(page_text_chunks)
                        # Exact heading match wins
                        try:
                            if q_ns and any(q_ns in _norm_ns(hv) for hv in headings):
                                exact_matches.append(pn)
                                continue
                        except Exception:
                            pass
                        tok_sc = _overlap2(qt, bag)
                        ns_sc = 5.0 if (q_ns and q_ns in _norm_ns(bag) and len(q_ns) >= 10) else 0.0
                        head_bonus = 0.0
                        try:
                            for hv in headings:
                                hns = _norm_ns(hv)
                                if hns and (hns == q_ns or q_ns in hns or hns in q_ns):
                                    head_bonus = max(head_bonus, 10.0)
                                else:
                                    htok = set(_tokens2(hv))
                                    inter = len([t for t in qt if t in htok])
                                    if htok and inter / max(1, len(htok)) >= 0.6:
                                        head_bonus = max(head_bonus, 6.0)
                        except Exception:
                            pass
                        step_boost = 1.0 if (tok_sc >= 1 and len(page_text_chunks) >= 2) else 0.0
                        table_bonus = min(8.0, (float(table_cells) / 30.0)) if (tok_sc >= 1 or head_bonus > 0 or ns_sc > 0) else 0.0
                        toc_pen = 0.0
                        try:
                            lines = [ln.strip() for ln in (bag.splitlines() if isinstance(bag, str) else []) if ln.strip()]
                            if lines:
                                dotleaders = sum(1 for ln in lines if _re5.search(r"\.{3,}", ln))
                                trailing_nums = sum(1 for ln in lines if _re5.search(r"\b\d{1,3}\s*$", ln))
                                ratio = (dotleaders + trailing_nums) / max(1, len(lines))
                                if head_bonus < 8.0 and ratio >= 0.3:
                                    toc_pen = min(6.0, 12.0 * ratio)
                        except Exception:
                            pass
                        sc = tok_sc + ns_sc + head_bonus + step_boost + table_bonus - toc_pen
                        if sc > best_sc:
                            best_sc = sc; best = pn
                if exact_matches:
                    return sorted(set(exact_matches))[0]
                return best if best_sc > 0 else None

            json_best_page = _json_best_page_for_query(json_name, query)
            if json_best_page is not None:
                target_page = int(json_best_page)
                # Hydrate page-specific text
                json_candidates_hy = [
                    config.OUTPUT_DIRECTORY / json_name,
                    (_P(config.BASE_DIR).parent / "output" / json_name),
                ]
                for jp in json_candidates_hy:
                    if not jp.exists():
                        continue
                    data_hy = _safe_json_load(jp) or {}
                    for p_hy in (data_hy.get("pages") or []):
                        try:
                            pn_hy = int(p_hy.get("page") or p_hy.get("page_number") or -1)
                        except Exception:
                            pn_hy = -1
                        if pn_hy != target_page:
                            continue
                        chunks = []
                        if p_hy.get("text"):
                            chunks.append(p_hy.get("text") or "")
                        if p_hy.get("md"):
                            chunks.append(p_hy.get("md") or "")
                        for it in (p_hy.get("items") or []):
                            t = (it.get("type") or it.get("item_type") or "").lower()
                            if t in ("text", "heading"):
                                chunks.append((it.get("value") or it.get("md") or ""))
                            elif t == "table":
                                rows = it.get("rows") or []
                                for r in rows:
                                    try:
                                        chunks.append("\t".join(str(c) for c in r))
                                    except Exception:
                                        chunks.append(" ".join(str(c) for c in r))
                        page_text = "\n".join([c for c in chunks if isinstance(c, str) and c.strip()])
                        break
                    if page_text:
                        break
        except Exception:
            pass

    # Now choose final images; if target_page is known, prefer images from that page or page screenshot
    final_images: List[Dict[str, Any]] = []
    if target_page is not None:
        # Keep only images from the primary file and same page
        same_page_imgs = [im for im in filtered_images if int(im.get("page_number") or -1) == target_page]
        final_images = same_page_imgs[:6] if is_visual else same_page_imgs[:3]
        if not final_images:
            # Screenshot fallback
            try:
                from pathlib import Path as _P_img
                prefix = _derive_image_prefix(json_name if 'json_name' in locals() else primary_file)
                shot_pref = _P_img(config.OUTPUT_DIRECTORY) / "images" / f"{prefix}_page_{target_page}.jpg"
                shot_gen = _P_img(config.OUTPUT_DIRECTORY) / "images" / f"page_{target_page}.jpg"
                shot = shot_pref if shot_pref.exists() else shot_gen
                if shot.exists():
                    sname = shot.name
                    final_images = [{
                        "filename": sname,
                        "url": f"/output/images/{sname}",
                        "score": 1.0,
                        "model_used": "page-screenshot",
                        "detailed_description": "",
                        "confidence": "high",
                        "priority": "primary",
                        "page_number": target_page,
                        "page_rank": 2
                    }]
            except Exception:
                pass
        # If still empty, fallback to general filtered images
        if not final_images:
            final_images = filtered_images[:6] if is_visual else filtered_images[:3]
    else:
        final_images = filtered_images[:6] if is_visual else filtered_images[:3]

    context_text = "\n\n".join(context_lines)
    
    if is_visual:
        if final_images:
            image_descriptions = []
            for img in final_images[:3]:
                desc = img.get("detailed_description", "")
                admin_idx = img.get("admin_index", "unknown")
                if desc and desc != "Description unavailable":
                    image_descriptions.append(f"Image from {admin_idx}/{img.get('filename', 'unknown file')}: {desc}")
            
            if context_text.strip():
                combined_context = f"Text content:\n{context_text}\n\nImage descriptions:\n" + "\n".join(image_descriptions)
                answer = await _llm_call(combined_context, query + " (Focus on visual elements and provide details about the images shown)")
            else:
                if image_descriptions:
                    answer = await _llm_call("\n".join(image_descriptions), query + " (Based on the images found)")
                else:
                    answer = "I found some relevant images for your query across multiple admin documents."
        else:
            if context_text.strip():
                answer = await _llm_call(context_text, query)
            else:
                return "I couldn't find any relevant visual content for your query."
    else:
        if not context_text.strip() and not page_text.strip():
            if final_images:
                answer = "I found some relevant images for your query, but no text content was available across the admin documents."
            else:
                return "The answer is not available in the provided context."
        else:
            to_send = page_text.strip() or context_text
            answer = await _llm_call(to_send, query)

    return {
        "answer": answer,
        "images": final_images,
        "query_type": "visual" if is_visual else "text",
        "context_sources": {
            "indexes_searched": len(index_names),
            "text_available": bool((page_text or context_text).strip()),
            "images_found": len(final_images),
            "primary_file": primary_file,
            "secondary_files": secondary_files
        }
    }
    
    
    primary_images = []
    secondary_images = []
    
    for h in top_hits:
        meta = h.get("metadata", {})
        fname = meta.get("file_name") or meta.get("heading") or "unknown_source"
        
        if meta.get("type") == "image":
            img_source_file = meta.get("source_file", "")
          
            base_file = img_source_file.split("_page")[0] if "_page" in img_source_file else img_source_file.split(".")[0]
            
            img_data = {
                "filename": meta.get("filename") or meta.get("source_file", "unknown_image"),
                "url": meta.get("url"),
                "score": h.get("score")
            }
            
           
            if primary_file and (base_file in primary_file or primary_file in base_file):
                primary_images.append(img_data)
            elif any(base_file in sf or sf in base_file for sf in secondary_files):
                secondary_images.append(img_data)
    
   
    if secondary_files and len(secondary_images) > 0:
        
        all_images.extend(primary_images[:2])  
        all_images.extend(secondary_images[:1])  
    else:
        
        all_images.extend(primary_images[:3])
    
   
    all_images = all_images[:3]


    if not context_lines:
        if all_images:
           
            return {
                "answer": "Here are the related images from your documents:",
                "images": all_images
            }
        return "The answer is not available in the provided context."

    context_text = "\n\n---\n\n".join(context_lines)
    llm_response = await _llm_call(context_text, query)
    
    return {
        "answer": llm_response,
        "images": all_images
    }
