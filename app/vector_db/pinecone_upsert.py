from typing import Dict
from llama_index.node_parser import SemanticSplitterNodeParser
from llama_index.ingestion import IngestionPipeline
from llama_index.readers.schema import Document
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores import PineconeVectorStore
from llama_index import VectorStoreIndex, ServiceContext
from llama_index.retrievers import VectorIndexRetriever
from pinecone.grpc import PineconeGRPC
import requests
import json
import os
import dotenv

dotenv.load_dotenv()

# async def enrich_page_content(page):
#     full_text = page["text"].strip()
#     return full_text.strip()

async def combine_page_content(page: Dict) -> str:
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

async def load_documents_from_json(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("\n\n",data,"\n\n")
    documents = []
    for page in data.get("pages", []):
        enriched_text = await combine_page_content(page)
        metadata = {
            "page_number": page["page_number"],
            "file_name": data["metadata"]["file_name"]
        }
        documents.append(Document(text=enriched_text, metadata=metadata))
    print(f"\n\nLoaded {len(documents)} documents from {json_path}\n\n")
    return documents

async def embedding(model_name="BAAI/bge-small-en-v1.5", device="cpu", embed_batch_size=8):
    return HuggingFaceEmbedding(
        model_name=model_name,
        device=device,
        embed_batch_size=embed_batch_size
    )

async def upsert_documents_to_pinecone(documents_path, index_name = "llama-integration"):
    
    documents = await load_documents_from_json(documents_path)
    try:
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        pc = PineconeGRPC(api_key=pinecone_api_key)
        print(f"Connecting to Pinecone index: {index_name}")
        pinecone_index = pc.Index(index_name)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)
        print(f"Loaded Pinecone index: {pinecone_index.describe_index_stats()}")
        embed_model = await embedding()
        print("Using embedding model")
        pipeline = IngestionPipeline(
            transformations=[
                SemanticSplitterNodeParser(
                    buffer_size=1,
                    breakpoint_percentile_threshold=95,
                    embed_model=embed_model,
                    ),
                embed_model,
                ],
                vector_store=vector_store  # Our new addition
            )
        print("Starting upsert pipeline")
        pipeline.run(documents=documents)
        print(pinecone_index.describe_index_stats())
        return pinecone_index.describe_index_stats()
    
    except Exception as e:
        print(f"Error during upsert: {e}")
        return {"error": str(e)}

async def llm_call(retrieved_text):
    # Your Groq API key
    groq_api_key = os.getenv("GROQ_API_KEY")

    # Choose model available from Groq
    model = "llama3-8b-8192"

    # Define headers
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }

    # Create prompt
    prompt = f"Format and summarize the following content:\n\n{retrieved_text}"

    # Construct payload
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that formats and improves clarity of text."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 512
    }

    try:
        # Send request
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload
        )

        # Parse response
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    except requests.exceptions.RequestException as e:
        print(f"Error during LLM call: {e}")
        return {"error": str(e)}

async def retrival(query, index_name="llama-integration", top_k=5):
    try:
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        pc = PineconeGRPC(api_key=pinecone_api_key)
        
        pinecone_index = pc.Index(index_name)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)
        
        embed_model = await embedding()
        
        service_context = ServiceContext.from_defaults(llm=None, embed_model=embed_model)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
        
        retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)
        nodes = retriever.retrieve(query)
        
        retrieved_text = "\n\n".join([node.node.text for node in nodes])
        results = await llm_call(retrieved_text)
        return results

    except Exception as e:
        print(f"Error during retrieval: {e}")
        return {"error": str(e)}