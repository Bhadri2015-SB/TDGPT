from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import dotenv
import requests
from pinecone import Pinecone, ServerlessSpec

from app.vector_db.upsert_image import search_images

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

# Load environment variables
dotenv.load_dotenv()


def _safe_json_load(path: Path) -> Optional[Dict[str, Any]]:
    """Safely load JSON from path, return None if file doesn't exist or can't be parsed."""
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _derive_image_prefix(file_name: str) -> str:
    
    try:
        base = file_name
        if base.lower().endswith('.json'):
            base = base[:-5]
        for ext in ('.pdf',):
            if base.lower().endswith(ext):
                base = base[: -len(ext)]
                break
        base = base.strip().replace(' ', '_')
        return base
    except Exception:
        return file_name


def _ensure_images_namespaced(json_path: Path) -> None:
    """Ensure image filenames in JSON are properly namespaced to avoid collisions."""
    data = _safe_json_load(json_path)
    if not data:
        return
    changed = False
    title_norm = re.sub(r"[^\w\-_.]", "_", data.get("title", json_path.stem)) or "doc"
  
    images_dir = json_path.parent / "images"

    
    top_images = data.get("images") or []
    for img in top_images:
        filename = img.get("filename") or img.get("name") or ""
        if filename and not filename.startswith(title_norm):
            img_name = filename
            img["filename"] = f"{title_norm}_{img_name}"
            changed = True

   
    for page in data.get("pages", []):
        pnum = page.get("page") or page.get("page_number")
        imgs = page.get("images") or []
        counter = 1
        for img in imgs:
            filename = img.get("filename") or img.get("name")
            if not filename:
                continue
         
            if filename.startswith(title_norm) and ("_img_p" in filename or f"_page_{pnum}" in filename):
                continue
            ext = ''
            if '.' in filename:
                ext = filename[filename.rfind('.'):]
            new_name = f"{title_norm}_img_p{pnum}_{counter}{ext}" if pnum else f"{title_norm}_{filename}"
            img["filename"] = new_name
            counter += 1
            changed = True

    if changed:
        try:
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
          
            if images_dir.exists():
              
                referenced = []
                for page in data.get("pages", []):
                    for im in (page.get("images") or []):
                        original = im.get("name") or im.get("original_name") or None
                        newf = im.get("filename") or im.get("name")
                        if newf and original and original != newf:
                            referenced.append((original, newf))
                        elif newf and not original:
                           
                            prev = im.get("_old") or None
                            if prev and prev != newf:
                                referenced.append((prev, newf))
            
                for im in (data.get("images") or []):
                    original = im.get("name") or im.get("original_name") or None
                    newf = im.get("filename") or im.get("name")
                    if newf and original and original != newf:
                        referenced.append((original, newf))
                for old, new in referenced:
                    try:
                        src = images_dir / old
                        dst = images_dir / new
                        if src.exists() and not dst.exists():
                            src.rename(dst)
                    except Exception:
                        pass
        except Exception:
            pass


async def get_available_indexes() -> List[str]:
    """List all Pinecone index names."""
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    return pc.list_indexes().names()


def _clean_name(name: str) -> str:
    """Clean admin name for Pinecone index naming conventions."""
    
    clean = re.sub(r"[^\w\-]", "-", name.lower())
   
    clean = re.sub(r"-+", "-", clean)
   
    clean = clean.strip("-")
  
    if not clean:
        clean = "default"
    return clean[:50]  


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
    """Combine text content from a page structure into a single string."""
    parts = []
    
    
    if page.get("text"):
        parts.append(page["text"])
    
  
    if page.get("md"):
        parts.append(page["md"])
    

    for item in page.get("items", []):
        if item.get("type") == "heading" and item.get("value"):
            parts.append(f"## {item['value']}")
        elif item.get("type") == "text" and item.get("value"):
            parts.append(item["value"])
        elif item.get("md"):
            parts.append(item["md"])
   
    for image in page.get("images", []):
        for ocr_entry in image.get("ocr", []):
            if ocr_entry.get("text"):
                parts.append(f"[OCR] {ocr_entry['text']}")
    
    return "\n\n".join(parts)


async def _load_pdf_like_documents(json_path: Path) -> List[Document]:
    """Generic loader used for PDF, Word, etc. that follow 'pages' structure."""
    data = _safe_json_load(json_path) or {}
    docs = []
    
    title = data.get("title", json_path.stem)
    metadata_base = data.get("metadata", {})
    
    for page in data.get("pages", []):
        try:
            page_num = int(page.get("page", 0))
            content = await _combine_page_content(page)
            
            if content.strip():
                docs.append(Document(
                    text=content,
                    metadata={
                        **metadata_base,
                        "file_name": title,
                        "page_number": page_num,
                    }
                ))
        except Exception as e:
            print(f"Error processing page in {json_path}: {e}")
            continue
    
    return docs


async def _index_images_from_word_document(json_path: Path, admin_name: str) -> Dict[str, Any]:
    """Index images from Word document JSON structure into the shared Pinecone index using CLIP embeddings."""
    from app.vector_db.upsert_image import embed_image
    import os
    
    data = _safe_json_load(json_path) or {}
    fname = data.get("metadata", {}).get("file_name", json_path.name)
    pages = data.get("pages", [])
    
    index_name_clean = config.SHARED_PINECONE_INDEX
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    
   
    existing = pc.list_indexes().names()
    if index_name_clean not in existing:
        try:
            pc.create_index(
                name=index_name_clean,
                dimension=384,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        except Exception as ce:
            print(f"[Image-Index-Create-Warning] {ce}")
            existing = pc.list_indexes().names()
            if index_name_clean not in existing:
                return {"processed_images": 0, "errors": [f"Shared index '{index_name_clean}' unavailable: {ce}"]}
    
    idx = pc.Index(index_name_clean)
    vectors = []
    processed_images = 0
    errors = []
    
    base_dir = json_path.parent  
    
   
    for page in pages:
        page_num = page.get("page", 0)
        for img in page.get("images", []):
            img_filename = img.get("filename", "") or img.get("name", "")
            if not img_filename:
                continue
            
            img_path = base_dir / "images" / img_filename
            if not img_path.exists():
                errors.append(f"Image file not found: {img_path}")
                continue
                
            try:
               
                vec = await embed_image(str(img_path))
                
               
                ocr_text = ""
                if "ocr" in img and isinstance(img["ocr"], list):
                    ocr_texts = [ocr_item.get("text", "") for ocr_item in img["ocr"] if ocr_item.get("text")]
                    ocr_text = " ".join(ocr_texts)
                
              
                metadata = {
                    "type": "image",
                    "source_file": fname,
                    "page_number": page_num,
                    "filename": img_filename,
                    "url": f"/output/images/{img_filename}",
                    **({"caption": img.get("caption")} if img.get("caption") else {}),
                    **({"ocr_text": ocr_text} if ocr_text else {}),
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


async def _detect_category_from_extracted_file(path: Path) -> str:
    """Infer the original file category from extracted JSON."""
    try:
        data = _safe_json_load(path) or {}
        
      
        metadata = data.get("metadata", {})
        file_name = metadata.get("file_name", path.name.lower())
        
      
        if file_name.endswith(('.pdf',)):
            return "PDF"
        
        
        if "pages" in data:
            return "PDF"  
        elif "worksheets" in data:
            return "EXCEL"
        elif "slides" in data:
            return "PPT"
        else:
            return "UNKNOWN"
    except Exception:
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
        print(f"[INGEST] Start processing doc: {path.name}")
 
        try:
            _ensure_images_namespaced(path)
        except Exception:
            pass
            
      
        docs = await _load_pdf_like_documents(path)
    except Exception as e:
        return {
            "admin_id": admin_id,
            "file_name": file_base,
            "status": "Embedding failed",
            "message": f"Doc build error: {e}",
        }


    index_name_clean = config.SHARED_PINECONE_INDEX

    try:
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        existing = pc.list_indexes().names()
        if index_name_clean not in existing:
            try:
                pc.create_index(
                    name=index_name_clean,
                    dimension=384,
                    metric="cosine",
                    spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                )
            except Exception as ce:
                
                print(f"[Index-Create-Warning] Could not create index '{index_name_clean}': {ce}")
                existing = pc.list_indexes().names()
                if index_name_clean not in existing:
                    return {
                        "admin_id": admin_id,
                        "file_name": file_base,
                        "status": "Embedding failed",
                        "message": f"Index '{index_name_clean}' not available and creation failed: {ce}",
                    }

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

        print(f"[INGEST] Embedding {len(docs)} chunks for {file_base} into index {index_name_clean}")
        await asyncio.to_thread(pipeline.run, documents=docs, show_progress=False)
        print(f"[INGEST] Text embedding complete: {file_base}")


        image_result = {"processed_images": 0, "errors": []}
        try:
            image_result = await _index_images_from_word_document(path, admin_name)
            if image_result.get("processed_images"):
                print(f"[INGEST] Indexed {image_result.get('processed_images')} images for {file_base}")
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
       
        index_name_clean = config.SHARED_PINECONE_INDEX
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
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
    """Make LLM call using Groq API with retrieved context."""
    import json
    
    system_prompt = """
    You are an intelligent assistant that provides accurate and helpful responses based on the provided context.
    
    Instructions:
    1. Answer the user's question using ONLY the information provided in the context
    2. If the context doesn't contain enough information to answer the question, say so
    3. Be concise but comprehensive
    4. If there are multiple relevant pieces of information, organize them clearly
    5. Do not make up information that isn't in the context
    """
    
    user_prompt = f"""
    Context Information:
    {retrieved_text}
    
    Question: {query}
    
    Please provide a helpful answer based on the context above.
    """
    
    try:
        #  Groq API for LLM call
        headers = {
            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "model": config.GROQ_MODEL,
            "temperature": 0.1,
            "max_tokens": 1000
        }
        
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        else:
            print(f"Groq API error: {response.status_code} - {response.text}")
            return "I apologize, but I'm unable to process your request at the moment due to a technical issue."
            
    except Exception as e:
        print(f"LLM call error: {e}")
        return "I apologize, but I encountered an error while processing your request."


def _is_visual_query(query: str) -> bool:
    """Check if a query is asking for visual/image content."""
    visual_keywords = [
        "image", "picture", "photo", "diagram", "chart", "graph", 
        "figure", "illustration", "screenshot", "visual", "show me",
        "what does it look like", "appearance", "drawing", "sketch"
    ]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in visual_keywords)


async def get_admin_indexes_from_db(db: AsyncSession) -> List[str]:
    """Fetch all admin names from database and return their corresponding Pinecone index names."""
    try:
        result = await db.execute(select(Admin.admin_name))
        admin_names = result.scalars().all()
        return [_clean_name(name) for name in admin_names]
    except Exception as e:
        print(f"Error fetching admin indexes from DB: {e}")
        return []


async def retrieval_all_admins(
    query: str,
    db: AsyncSession,
    admin_name: Optional[str] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    Enhanced retrieval that automatically handles both text and image search.
    
    - For visual queries: prioritizes image results + relevant text context
    - For text queries: prioritizes text with related images as context
    - Returns unified response with both text answer and single accurate image URL
    """
    try:
       
        index_name_clean = config.SHARED_PINECONE_INDEX

        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        available_indexes = pc.list_indexes().names()
        if index_name_clean not in available_indexes:
            return {
                "error": f"Shared Pinecone index '{index_name_clean}' not found. Available: {available_indexes}",
                "query": query,
                "response": {
                    "answer": f"Shared Pinecone index '{index_name_clean}' not found.",
                    "images": []
                }
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
               
                exact_matches: List[int] = []
               
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
                    
                        items2 = p.get("items") or []
                        page_text_chunks = []
                    
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
                            if it.get("type") in ("text", "heading"):
                                page_text_chunks.append((it.get("value") or it.get("md") or ""))
                      
                        for im in (p.get("images") or []):
                            a = im.get("anchors") or {}
                            page_text_chunks.append(((a.get("heading") or {}).get("text") or ""))
                            page_text_chunks.append(((a.get("above_text") or {}).get("text") or ""))
                            page_text_chunks.append(((a.get("below_text") or {}).get("text") or ""))
                            for e in (im.get("ocr") or []):
                                page_text_chunks.append(e.get("text") or "")
                        bag = " \n ".join(page_text_chunks)
                      
                        try:
                            if q_ns and (q_ns in _norm_ns(bag)):
                                exact_matches.append(pn)
                                continue
                        except Exception:
                            pass
                     
                        tok_sc = _overlap2(qt, bag)
                        ns_sc = 5.0 if (q_ns and q_ns in _norm_ns(bag) and len(q_ns) >= 10) else 0.0
                      
                        step_boost = 1.0 if ("step" in bag.lower() and tok_sc >= 1) else 0.0
                        sc = tok_sc + ns_sc + step_boost
                        if sc > best_sc:
                            best_sc = sc
                            best = pn
                if exact_matches:
                  
                    return sorted(set(exact_matches))[0]
                return best if best_sc > 0 else None

    
            json_best_page = _json_best_page_for_query(primary_file, query) if primary_file else None
            if json_best_page is not None:
                best_node_page = json_best_page
                primary_pages = [json_best_page]
        except Exception:
            pass

     
        chosen_image = None
        target_file = best_node_file or primary_file
        target_page = best_node_page or (primary_pages[0] if primary_pages else None)

        if target_file and target_page is not None:
            try:
                from app.vector_db.upsert_image import search_images
                all_images = await search_images(query, index_name_clean, top_k=12)
            except Exception as e:
                print(f"[Image-Search-ERROR] {e}")
                all_images = []

        
            page_linked_images: List[Dict[str, Any]] = []
            for img in all_images:
                try:
                    img_page = img.get("page_number")
                    if img_page is not None and int(float(img_page)) == int(target_page):
                        page_linked_images.append(img)
                except Exception:
                    pass
            if page_linked_images:
                page_linked_images.sort(key=lambda x: float(x.get("score", 0) or 0.0), reverse=True)
                chosen_image = page_linked_images[0]

            if not chosen_image and all_images:
                file_images = []
                for img in all_images:
                    src = img.get("source_file", "") or ""
                    if src and (target_file in src or src in target_file):
                        file_images.append(img)
                if file_images:
                    file_images.sort(key=lambda x: float(x.get("score", 0) or 0.0), reverse=True)
                    chosen_image = file_images[0]

            if not chosen_image:
                try:
                    from pathlib import Path as _P_fallback
                    json_candidates = [
                        config.OUTPUT_DIRECTORY / target_file,
                        (_P_fallback(config.BASE_DIR).parent / "output" / target_file),
                    ]
                    for jp in json_candidates:
                        if not jp.exists():
                            continue
                        data = _safe_json_load(jp) or {}
                        for p in (data.get("pages") or []):
                            try:
                                pn = int(p.get("page") or p.get("page_number") or -1)
                            except Exception:
                                pn = -1
                            if pn != int(target_page):
                                continue
                            imgs = [im for im in (p.get("images") or []) if (im.get("type") or im.get("img_type")) != "full_page_screenshot"]
                            
                            if imgs:
                                try:
                                    imgs.sort(key=lambda im: (
                                        float(im.get("y", 0) or 0.0),
                                        -float(im.get("width", 0) or 0.0)
                                    ))
                                except Exception:
                                    pass
                                pick = None
                              
                                for im in imgs:
                                    w = float(im.get("width", 0) or 0.0)
                                    h = float(im.get("height", 0) or 0.0)
                                    if w >= 40 and h >= 40: 
                                        pick = im
                                        break
                                if not pick:
                                    pick = imgs[0]
                                name = pick.get("name") or pick.get("filename") or ""
                                if name:
                                    chosen_image = {
                                        "filename": name,
                                        "url": f"/output/images/{name}",
                                        "score": 1.0,
                                        "page_number": pn,
                                        "model_used": "json-inline"
                                    }
                                    break
                          
                            if not chosen_image:
                                try:
                                    prefix = _derive_image_prefix(target_file)
                                except Exception:
                                    prefix = None
                                from pathlib import Path as _P2
                                shot_pref = _P2(config.OUTPUT_DIRECTORY) / "images" / f"{prefix}_page_{pn}.jpg" if prefix else None
                                shot_gen = _P2(config.OUTPUT_DIRECTORY) / "images" / f"page_{pn}.jpg"
                                shot = None
                                if shot_pref and shot_pref.exists():
                                    shot = shot_pref
                                elif shot_gen.exists():
                                    shot = shot_gen
                                if shot and shot.exists():
                                    chosen_image = {
                                        "filename": shot.name,
                                        "url": f"/output/images/{shot.name}",
                                        "score": 0.95,
                                        "page_number": pn,
                                        "model_used": "page-screenshot"
                                    }
                                    break
                        if chosen_image:
                            break
                except Exception as e:
                    print(f"[Image-JSON-Fallback-ERROR] {e}")

    
            if not chosen_image and all_images:
                try:
                    all_images.sort(key=lambda x: float(x.get("score", 0) or 0.0), reverse=True)
                    fallback = all_images[0]
                    chosen_image = {
                        "filename": fallback.get("filename"),
                        "url": fallback.get("url"),
                        "score": fallback.get("score"),
                        "page_number": fallback.get("page_number"),
                        "model_used": "vector-fallback"
                    }
                except Exception:
                    pass

     
        images = []
        if chosen_image:
            images = [{
                "filename": chosen_image.get("filename", ""),
                "url": chosen_image.get("url", ""),
                "score": chosen_image.get("score", 0),
                "page_number": chosen_image.get("page_number", 0)
            }]

      
        if not retrieved_text.strip():
            if images:
                return {
                    "query": query,
                    "response": {
                        "answer": "Here is the related image from your documents:",
                        "images": images
                    }
                }
            return {
                "query": query,
                "response": {
                    "answer": "No relevant information found in the documents.",
                    "images": []
                }
            }

        llm_response = await _llm_call(retrieved_text, query)

        return {
            "query": query,
            "response": {
                "answer": llm_response,
                "images": images
            }
        }

    except Exception as e:
        print(f"Error in retrieval_all_admins: {e}")
        return {
            "error": f"Retrieval failed: {str(e)}",
            "query": query,
            "response": {
                "answer": "An error occurred while searching the documents.",
                "images": []
            }
        }





async def get_admin_indexes_from_db(db: AsyncSession) -> List[str]:
    """
    Return a list of Pinecone index names (cleaned) that correspond to
    admin_name values in the Admin table *and* actually exist in Pinecone.
    """
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    existing = set(pc.list_indexes().names())

    res = await db.execute(select(Admin.admin_name))
    admin_names = [row[0] for row in res.all()]

    out: List[str] = []
    for name in admin_names:
        cleaned = _clean_name(name)
        if cleaned in existing:
            out.append(cleaned)
    return out
