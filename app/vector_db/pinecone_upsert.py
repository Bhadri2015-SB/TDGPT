from pathlib import Path
from typing import Any, Dict, List
from llama_index.node_parser import SemanticSplitterNodeParser
from llama_index.ingestion import IngestionPipeline
from llama_index.readers.schema import Document
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores import PineconeVectorStore
from llama_index import VectorStoreIndex, ServiceContext
from llama_index.retrievers import VectorIndexRetriever
from pinecone import Pinecone, ServerlessSpec
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


async def flatten_json(y: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    """
    Recursively flattens a nested dictionary.
    Nested dicts/lists are unrolled with keys like "shared_on.twitter"
    """
    out = {}

    def flatten(x, name=''):
        if isinstance(x, dict):
            for a in x:
                flatten(x[a], f'{name}{a}.')
        elif isinstance(x, list):
            for i, a in enumerate(x):
                flatten(a, f'{name}{i}.')
        else:
            out[name[:-1]] = str(x)  # convert all values to string

    flatten(y, prefix)
    return out


async def load_json_to_documents_generic(file_path: str) -> List[Document]:
    """Load a general JSON array and convert it to LlamaIndex Documents."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("JSON root must be a list of records.")

    documents = []
    for record in data:
        flat_record = await flatten_json(record)

        # Join all text fields into a large body for embedding
        content = "\n".join(
            f"{key.replace('.', ' ').title()}: {value}"
            for key, value in flat_record.items()
            if not key.lower().endswith(('id', 'views', 'likes')) and len(str(value).strip()) > 0
        )

        metadata = {k: v for k, v in flat_record.items() if k.lower().endswith(('id', 'title', 'author', 'category'))}

        doc = Document(text=content, metadata=metadata)
        documents.append(doc)

    return documents

async def load_documents_from_json(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # print("\n\n",data,"\n\n")
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


async def load_documents_from_multi_table_json(json_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    documents = []

    for table_name, table_info in data.items():
        columns = table_info.get("columns", [])
        rows = table_info.get("data", [])

        for row in rows:
            content_lines = [f"{col}: {row.get(col, '')}" for col in columns]
            content = f"Table: {table_name}\n" + "\n".join(content_lines)

            metadata = {
                "table": table_name,
                "primary_id": row.get(f"{table_name}_id")
            }

            documents.append(Document(text=content.strip(), metadata=metadata))
    print(documents)
    return documents

async def upsert_documents_to_pinecone(documents_path,user_id,category, index_name = "llama-integration"):
    if category=="Excel" or "SQLITE" or "SQL_SCRIPT":#documents_path.endswith("table.json"):
        documents = await load_documents_from_multi_table_json(documents_path)
    elif documents_path.endswith(".json.json"):
        documents = await load_json_to_documents_generic(documents_path)
    else:
        documents = await load_documents_from_json(documents_path)
    try:
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        pc = Pinecone(api_key=pinecone_api_key)
  
        if index_name not in pc.list_indexes().names():
            pc.create_index(
                name=index_name,
                dimension=384, 
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )

        pinecone_index = pc.Index(index_name)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)

        embed_model = await embedding()

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

        pipeline.run(documents=documents)
        path=Path(documents_path)
        return {
            "user_id": user_id,
            "file_name": path.name.removesuffix(".json"),
            "status": "Processed",
            "message": "File successfully processed and embedded.",
            # "time_taken_to_process": total_time or int(time.time() - start_time)
        }
            # return None
    
    except Exception as e:
        print(f"Error during upsert: {e}")
        path=Path(documents_path)
        return {
            "user_id": user_id,
            "file_name": path.name.removesuffix(".json"),
            "status": "Embedding failed",
            "message": f"Error during upsert: {e}",
            # "time_taken_to_process": total_time or int(time.time() - start_time)
        }
    
async def llm_call(retrieved_text, query):
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
    # prompt = f"Format and summarize the following content:\n\n{retrieved_text}"
    systemPrompt = """You are an expert domain assistant that strictly adheres to the provided context to generate precise, accurate, and context-grounded answers.
            Guidelines:
            - Use only the retrieved context to answer the user's query.
            - Do NOT hallucinate or fabricate any information.
            - If the answer cannot be determined from the context, respond with:
            "The answer is not available in the provided context."
            - Preserve all code formatting, numbers, and technical structure.
            - Prefer clarity and completeness over brevity.
            - When helpful, use bullet points, step-by-step instructions, or short code examples.
            - Never mention that context was provided — just answer naturally.
            """
    # Construct payload
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": systemPrompt},
            {"role": "user", "content": f"Context: {retrieved_text}\n\nUser Query: {query}"}
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
        # print(f"Response: {response.text}")
        # Parse response
        result = response.json()
        return result["choices"][0]["message"]["content"]
    
    except requests.exceptions.RequestException as e:
        print(f"Error during LLM call: {e}")
        return {"error": str(e)}

async def retrival(query, index_name="llama-integration", top_k=5):
    try:
        pinecone_api_key = os.getenv("PINECONE_API_KEY")
        pc = Pinecone(api_key=pinecone_api_key)
        # print(f"Connecting to Pinecone index: {index_name}")
        pinecone_index = pc.Index(index_name)
        vector_store = PineconeVectorStore(pinecone_index=pinecone_index)
        # print(f"Loaded Pinecone index: {pinecone_index.describe_index_stats()}")
        embed_model = await embedding()
        
        service_context = ServiceContext.from_defaults(llm=None, embed_model=embed_model)
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store, service_context=service_context)
        # print("Index created successfully")
        retriever = VectorIndexRetriever(index=index, similarity_top_k=top_k)
        nodes = retriever.retrieve(query)
        # print(f"Retrieved {len(nodes)} nodes for query: {query}")
        retrieved_text = "\n\n".join([node.node.text for node in nodes])
        results = await llm_call(retrieved_text, query)
        return results

    except Exception as e:
        print(f"Error during retrieval: {e}")
        return {"error": str(e)}