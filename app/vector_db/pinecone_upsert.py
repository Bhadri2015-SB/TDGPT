from pathlib import Path
import re
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

from app.core import config
from app.utils.file_handler import get_file_category

dotenv.load_dotenv()


async def get_available_indexes():
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    return pc.list_indexes().names()

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


async def flattened_dict_to_document(file_path) -> List[Document]:

    with open(file_path, 'r', encoding='utf-8') as f:
        flattened = json.load(f)
    lines = []
    for key, value in flattened.items():
        # Convert all values to string in case of numbers, bools etc.
        line = f"{key}: {str(value)}"
        lines.append(line)

    combined_text = "\n".join(lines)

    return [Document(text=combined_text, metadata={"file_name": Path(file_path).name.removesuffix(".json")})]


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

async def clean_name(name: str) -> str:
    # Remove all non-alphabetic characters (i.e., keep only letters)
    cleaned = re.sub(r'[^A-Za-z]', '', name)
    # Convert to lowercase
    return cleaned.lower()

async def sqlite_data_to_documents(file_path) -> List[Document]:

    with open(file_path, 'r', encoding='utf-8') as f:
        db_data = json.load(f)
    documents = []

    for table_name, table_info in db_data.items():
        columns = table_info.get("columns", [])
        rows = table_info.get("data", [])

        lines = []
        lines.append(f"Table: {table_name}")
        lines.append(f"Columns: {', '.join(columns)}")
        lines.append("Rows:")

        for row in rows:
            # Format each row as a readable string
            row_str = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"  - {row_str}")

        doc_text = "\n".join(lines)

        documents.append(Document(text=doc_text, metadata={"table_name": table_name}))

    return documents

async def excel_data_to_documents(file_path) -> List[Document]:
    """
    Converts structured Excel/CSV extracted content into LlamaIndex Documents.

    Args:
        extracted (Dict[str, Any]): Output from extract_excel_content().

    Returns:
        List[Document]: List of LlamaIndex Documents (one per sheet).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        extracted = json.load(f)
    content_by_sheet = {}
    file_name = extracted.get("metadata", {}).get("file_name", "unknown_file")

    for item in extracted.get("content", []):
        sheet = item["sheet"]
        row_number = item["row_number"]
        row_data = item["row_data"]

        row_text = f"Row {row_number}: " + ", ".join(f"{k}={v}" for k, v in row_data.items())

        if sheet not in content_by_sheet:
            content_by_sheet[sheet] = []
        content_by_sheet[sheet].append(row_text)

    documents = []
    for sheet, rows in content_by_sheet.items():
        doc_text = f"Sheet: {sheet}\n" + "\n".join(rows)
        documents.append(Document(text=doc_text, metadata={"file_name": file_name}))

    return documents

async def convert_markdown_json_to_documents(documents_path) -> List[Document]:

    with open(documents_path, 'r', encoding='utf-8') as f:
        parsed_data = json.load(f)

    documents = []
    metadata = parsed_data.get("metadata", {})
    content_blocks = parsed_data.get("content", [])

    current_text = ""
    current_heading = None

    for block in content_blocks:
        block_type = block.get("type")

        if block_type == "heading":
            # Save the previous section as a document
            if current_heading or current_text.strip():
                documents.append(Document(
                    text=current_text.strip(),
                    metadata={
                        "heading": current_heading,
                        "file_name": metadata.get("file_name", "unknown")
                    }
                ))
                current_text = ""
            current_heading = block.get("text", "Untitled Section")

        elif block_type == "paragraph":
            current_text += block.get("text", "") + "\n"

        elif block_type == "list":
            for item in block.get("items", []):
                current_text += f"- {item}\n"

        elif block_type == "code_block":
            language = block.get("language", "")
            code = block.get("code", "")
            current_text += f"```{language}\n{code}\n```\n"

    # Final section
    if current_heading or current_text.strip():
        documents.append(Document(
            text=current_text.strip(),
            metadata={
                "heading": current_heading,
                "file_name": metadata.get("file_name", "unknown")
            }
        ))

    return documents

async def ppt_data_to_documents(document_path) -> List[Document]:
    """
    Converts extracted PPT slide data to LlamaIndex Documents.

    Args:
        extracted (Dict[str, Any]): Output from extract_ppt_content().

    Returns:
        List[Document]: List of LlamaIndex Documents (one per slide).
    """

    with open(document_path, 'r', encoding='utf-8') as f:
            extracted = json.load(f)

    file_name = extracted.get("metadata", {}).get("file_name", "unknown.pptx")
    slides = extracted.get("slides", [])

    documents = []

    for slide in slides:
        slide_num = slide.get("slide_number", -1)
        text_blocks = slide.get("text_blocks", [])
        ocr_texts = slide.get("img_summary_texts", [])
        vision_descriptions = slide.get("img_vision_descriptions", [])

        sections = []

        if text_blocks:
            sections.append("Text Blocks:\n" + "\n".join(f"- {text}" for text in text_blocks))
        if ocr_texts:
            sections.append("Image OCR Texts:\n" + "\n".join(f"- {text}" for text in ocr_texts))
        if vision_descriptions:
            sections.append("Image Descriptions:\n" + "\n".join(f"- {desc}" for desc in vision_descriptions))

        doc_text = f"Slide {slide_num}\n" + "\n\n".join(sections)

        documents.append(Document(
            text=doc_text,
            metadata={
                "file_name": file_name,
                "slide_number": slide_num
            }
        ))

    return documents



async def upsert_documents_to_pinecone(documents_path,user_id,index_name = "llama-integration"):
    category = await get_file_category("."+documents_path.split('.')[-2])
    print(f"Category determined: {category}")
    if category in ( "SQLITE", "SQL_SCRIPT"):
        documents = await sqlite_data_to_documents(documents_path)
    elif category in ("Excel", "CSV"):
        documents = await excel_data_to_documents(documents_path)
    elif category=="JSON":
        documents = await flattened_dict_to_document(documents_path)
    elif category=="MD":
        documents = await convert_markdown_json_to_documents(documents_path)
    elif category=="PPT":
        documents = await ppt_data_to_documents(documents_path)
    else:
        documents = await load_documents_from_json(documents_path)
    try:
        pinecone_api_key = config.PINECONE_API_KEY
        pc = Pinecone(api_key=pinecone_api_key)
        name = await clean_name(index_name)
        if name not in pc.list_indexes().names():
            pc.create_index(
                name=name,
                dimension=384, 
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )

        pinecone_index = pc.Index(name)
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
    groq_api_key = config.GROQ_API_KEY

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
        
        # Check if request was successful
        if response.status_code != 200:
            print(f"API request failed with status {response.status_code}: {response.text}")
            return {"error": f"API request failed with status {response.status_code}"}
        
        # Parse response
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response: {e}")
            print(f"Response text: {response.text}")
            return {"error": f"Failed to parse API response: {str(e)}"}
        
        # Check if the response has the expected structure
        if "choices" not in result or len(result["choices"]) == 0:
            print(f"Unexpected response structure: {result}")
            return {"error": "Unexpected response structure from API"}
            
        if "message" not in result["choices"][0] or "content" not in result["choices"][0]["message"]:
            print(f"Unexpected message structure: {result}")
            return {"error": "Unexpected message structure from API"}
            
        return result["choices"][0]["message"]["content"]
    
    except requests.exceptions.RequestException as e:
        print(f"Error during LLM call: {e}")
        return {"error": str(e)}
    except KeyError as e:
        print(f"KeyError during response parsing: {e}")
        print(f"Response content: {response.text if 'response' in locals() else 'No response'}")
        return {"error": f"Response parsing error: {str(e)}"}
    except Exception as e:
        print(f"Unexpected error during LLM call: {e}")
        return {"error": str(e)}

async def retrival(query, index_name="llama-integration", top_k=5):
    try:
        pinecone_api_key = config.PINECONE_API_KEY
        pc = Pinecone(api_key=pinecone_api_key)
        name = await clean_name(index_name)
        # print(f"Connecting to Pinecone index: {index_name}")
        pinecone_index = pc.Index(name)
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