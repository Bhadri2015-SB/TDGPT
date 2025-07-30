
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
from app.utils.file_handler import get_file_category  # async

# If you call retrieval_all_admins() you'll need an AsyncSession from caller.
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Admin

dotenv.load_dotenv()




def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def get_available_indexes() -> List[str]:
    """List all Pinecone index names."""
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    return pc.list_indexes().names()


def _clean_name(name: str) -> str:
    """
    Pinecone index safe: keep alphanumerics only (lowercase).
    We keep digits to avoid collisions like AA1 vs AA2.
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
        docs.append(
            Document(
                text=enriched,
                metadata={"page_number": page.get("page_number"), "file_name": fname},
            )
        )
    return docs


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

    # try name like "file.pdf.json"
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

        return {
            "admin_id": admin_id,
            "file_name": file_base,
            "status": "Processed",
            "message": "File successfully processed and embedded.",
        }

    except Exception as e:
        print(f"[Upsert-ERROR] {path}: {e}")
        return {
            "admin_id": admin_id,
            "file_name": file_base,
            "status": "Embedding failed",
            "message": f"Error during upsert: {e}",
        }




async def _llm_call(retrieved_text: str, query: str) -> Any:
    """
    Call LLM only if we have non-empty context text.
    If no context: return strict fallback (no hallucinations).
    """
    if not retrieved_text.strip():
        return "The answer is not available in the provided context."

    groq_api_key = config.GROQ_API_KEY
    model = "llama3-8b-8192"

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "You are an expert domain assistant that strictly adheres to the provided context.\n"
        "- Use ONLY the retrieved context.\n"
        "- If answer not in context, say: 'The answer is not available in the provided context.'\n"
        "- Preserve technical formatting.\n"
        "- Provide clear, structured responses.\n"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{retrieved_text}\n\nUser Query: {query}"},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
    }

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            return {"error": f"Groq API {resp.status_code}: {resp.text}"}
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return {"error": "Unexpected Groq response format."}
    except Exception as e:
        return {"error": str(e)}




async def retrival(
    query: str,
    admin_name: Optional[str] = None,
    *,
    index_name: Optional[str] = None,
    top_k: int = 5,
) -> Any:
    """
    Retrieve matching chunks from **one** Pinecone index and run an LLM answer.

    Pass **index_name** if you want to target a known global index
    (e.g., "maindocs" or "llamaintegration").
    Otherwise we sanitize and use `admin_name`.
    """
    try:
     
        raw_name = index_name or admin_name or "defaultindex"
        index_name_clean = _clean_name(raw_name)

        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        if index_name_clean not in pc.list_indexes().names():
            return {"error": f"No Pinecone index named '{index_name_clean}'."}

        pinecone_index = pc.Index(index_name_clean)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)

        embed_model = _get_embed_model()
        service_context = ServiceContext.from_defaults(llm=None, embed_model=embed_model)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)

        retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)

        
        nodes = await asyncio.to_thread(retriever.retrieve, query)

        if not nodes:
            return "The answer is not available in the provided context."

        retrieved_text = "\n\n".join([n.node.text for n in nodes])
        return await _llm_call(retrieved_text, query)

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
    return out


async def retrieval_all_admins(
    query: str,
    db: AsyncSession,
    top_k_per_index: int = 3,
    top_k_final: int = 8,
) -> Any:
    """
    Query ALL admin Pinecone indexes, merge best results, send to LLM.
    Users don't need to know admin names.
    """
    index_names = await get_admin_indexes_from_db(db)
    if not index_names:
        return {"error": "No admin document indexes are available."}

    all_hits: List[Dict[str, Any]] = []
    for ix in index_names:
        try:
            hits = await _retrieval_single_index(query, ix, top_k=top_k_per_index)
            all_hits.extend(hits)
        except Exception as e:
            print(f"[MultiRetrieval] error querying index {ix}: {e}")

    if not all_hits:
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
    for h in top_hits:
        src_index = h["index_name"]
        meta = h.get("metadata", {})
        fname = meta.get("file_name") or meta.get("heading") or "unknown_source"
        snippet = (h["text"] or "").strip()
        if snippet:
            context_lines.append(f"[{src_index} :: {fname}]\n{snippet}")

    if not context_lines:
        return "The answer is not available in the provided context."

    context_text = "\n\n---\n\n".join(context_lines)
    return await _llm_call(context_text, query)
