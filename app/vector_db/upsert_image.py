import os
from pathlib import Path
from typing import List, Dict
import numpy as np
from transformers import CLIPProcessor, CLIPModel
from PIL import Image
from llama_index import Document, ServiceContext
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec
import torch
from app.core import config


clip_model = CLIPModel.from_pretrained("laion/CLIP-ViT-B-32-laion2B-s34B-b79K")
processor = CLIPProcessor.from_pretrained("laion/CLIP-ViT-B-32-laion2B-s34B-b79K")
clip_model = clip_model.to("cuda" if torch.cuda.is_available() else "cpu")

async def embed_image(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt").to(clip_model.device)
    with torch.no_grad():
        feat = clip_model.get_image_features(**inputs)
    
    
    embedding = feat.cpu().numpy()[0]
   
    embedding_384 = embedding[:384]  
    return embedding_384

async def debug_index_contents(index_name: str) -> Dict:
    """Debug function to check what's in the index"""
    try:
        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        
        if index_name not in pc.list_indexes().names():
            return {"error": f"Index {index_name} not found"}
        
        idx = pc.Index(index_name)
        
        
        stats = idx.describe_index_stats()
        
        
        zero_vector = [0.0] * 384
        results = idx.query(
            vector=zero_vector,
            top_k=10,
            include_metadata=True
        )
        
        image_count = 0
        text_count = 0
        sample_items = []
        
        for match in results.matches:
            metadata = match.metadata
            item_type = metadata.get("type", "unknown")
            if item_type == "image":
                image_count += 1
            else:
                text_count += 1
            
            sample_items.append({
                "id": match.id,
                "type": item_type,
                "metadata": metadata
            })
        
        return {
            "index_stats": stats,
            "sample_query_results": {
                "total_results": len(results.matches),
                "image_count": image_count,
                "text_count": text_count,
                "sample_items": sample_items
            }
        }
        
    except Exception as e:
        return {"error": str(e)}


async def search_images(query: str, index_name: str, top_k: int = 5) -> List[Dict]:
    """Search for images using CLIP text-to-image similarity"""
    try:
        pc = Pinecone(api_key=config.PINECONE_API_KEY)
        
       
        if index_name not in pc.list_indexes().names():
            return []
        
        idx = pc.Index(index_name)
        
        
        inputs = processor(text=[query], return_tensors="pt", padding=True).to(clip_model.device)
        with torch.no_grad():
            text_features = clip_model.get_text_features(**inputs)
        
       
        query_vector = text_features.cpu().numpy()[0]
        query_vector_384 = query_vector[:384] 
        
       
        results = idx.query(
            vector=query_vector_384.tolist(), 
            top_k=top_k,
            include_metadata=True,
            filter={"type": {"$eq": "image"}}
        )
        
        images = []
        for match in results.matches:
            metadata = match.metadata
            images.append({
                "source_file": metadata.get("source_file"),
                "url": metadata.get("url"),
                "score": match.score,
                "filename": metadata.get("filename"),
                "page_number": metadata.get("page_number"),  
                "full_path": metadata.get("full_path")
            })
        
        return images
        
    except Exception as e:
        print(f"Error searching images: {e}")
        return []


async def upsert_image_folder(images_dir: str, admin_name: str):
    """
    Upload images to the same index as the admin's text documents
    """
    from app.core import config
    from pinecone import Pinecone, ServerlessSpec
    import re
    
   
    index_name = config.SHARED_PINECONE_INDEX
    
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    
   
    if index_name not in pc.list_indexes().names():
        try:
            pc.create_index(name=index_name, dimension=384, metric="cosine",
                            spec=ServerlessSpec(cloud="aws", region="us-east-1"))
        except Exception as ce:
            print(f"[Image-Index-Create-Warning] {ce}")
            if index_name not in pc.list_indexes().names():
                return {
                    "admin_id": admin_name,
                    "file_name": f"images_from_{images_dir}",
                    "status": "Embedding failed",
                    "message": f"Shared index '{index_name}' not available and creation failed: {ce}",
                }
    
    idx = pc.Index(index_name)
    vectors = []
    processed_images = 0
    print(f"[IMG-INGEST] Scanning images in {images_dir} for admin {admin_name}")
    
    for img_path in Path(images_dir).rglob("*"):
        if img_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
            try:
                vec = await embed_image(img_path)
              
                import re as _re
                fname = img_path.name
                page_num = None
                m = _re.search(r"_img_p(\d+)_", fname)
                if m:
                    try:
                        page_num = int(m.group(1))
                    except Exception:
                        page_num = None
                metadata = {
                    "type": "image",
                    "source_file": img_path.name,
                    "full_path": str(img_path),
                    "url": f"/output/images/{img_path.name}",
                    "admin_name": admin_name,
                    **({"page_number": page_num} if page_num is not None else {})
                }
                vectors.append({"id": f"img::{img_path.name}", "values": vec.tolist(), "metadata": metadata})
                processed_images += 1
                if processed_images % 25 == 0:
                    print(f"[IMG-INGEST] {processed_images} images embedded so far...")
            except Exception as e:
                print(f"Error processing image {img_path}: {e}")
                continue
    
    if vectors:
        idx.upsert(vectors=vectors)
        print(f"[IMG-INGEST] Upserted {processed_images} images into index {index_name}")
    
    return {
        "admin_id": admin_name,
        "file_name": f"images_from_{images_dir}",
        "status": "Processed",
        "message": f"Successfully processed {processed_images} images into index '{index_name}'.",
    }


