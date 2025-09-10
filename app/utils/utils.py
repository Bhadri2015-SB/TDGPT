import os
import aiofiles
from typing import List, Dict, Optional
import requests
from app.core.config import IMAGE_OUTPUT_DIR
from app.core import config

# async def save_image(element, pdf_name, page_number, image_count):
#     os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)
#     image_path = os.path.join(IMAGE_OUTPUT_DIR, f"{pdf_name}_page_{page_number}_img_{image_count}.png")
#     image_data = getattr(element, "image", None)
#     if image_data and hasattr(image_data, "save"):
#         try:
           
#             import asyncio
#             loop = asyncio.get_running_loop()
#             await loop.run_in_executor(None, image_data.save, image_path)
#             return image_path
#         except Exception as e:
#             print(f" Error saving image on page {page_number} image {image_count}: {e}")
#     else:
#         print(f" No image data found on page {page_number} image {image_count}")
#     return None

async def summarize_text(text, groq_client, model):
    if not text.strip():
        return "No content to summarize."
    prompt = f"Summarize this content in 1-2 lines:\n{text[:3000]}"
    try:

        response = await groq_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f" Error during summarization: {e}")
        return "Summary not available due to an error."

# async def save_image_to_folder(image_bytes, filename, has_text):
#     folder = "img_summary" if has_text else "img_vision"
#     dir_path = os.path.join(IMAGE_OUTPUT_DIR, folder)
#     os.makedirs(dir_path, exist_ok=True)
#     image_path = os.path.join(dir_path, filename)
#     import aiofiles
#     async with aiofiles.open(image_path, "wb") as f:
#         await f.write(image_bytes)
#     return image_path


async def groq_chat_completion(
    messages: List[Dict[str, str]], 
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 512
) -> str:
    """
    Make a chat completion request to Groq API.
    """
    try:
        # Get API key
        groq_api_key = config.GROQ_API_KEY
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY not found in configuration")
        # Determine model list (primary + fallbacks)
        model_sequence = [model or config.GROQ_MODEL]
        for fb in getattr(config, "GROQ_MODEL_FALLBACKS", []):
            if fb not in model_sequence:
                model_sequence.append(fb)
        
        # Prepare headers
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        
        # Prepare messages
        chat_messages = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        
        chat_messages.extend(messages)
        
        last_error = None
        for mdl in model_sequence:
            # Prepare payload
            payload = {
                "model": mdl,
                "messages": chat_messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            # Make request
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload
            )
            # If request failed, try next model on decommission or 400-series
            if response.status_code != 200:
                last_error = f"API request failed with status {response.status_code}: {response.text}"
                # If model decommissioned, continue to fallback
                try:
                    data = response.json()
                    msg = str(data)
                except Exception:
                    msg = response.text
                if "model_decommissioned" in msg or "decommissioned" in msg or response.status_code in (400, 404):
                    continue
                # Other errors: break
                break
            # Parse response
            result = response.json()
            # Extract content
            if "choices" in result and len(result.get("choices", [])) > 0:
                message_obj = result["choices"][0].get("message", {})
                content = message_obj.get("content")
                if content:
                    return content
            # Unexpected structure; try next
            last_error = "Unexpected response structure from Groq API"
            continue

        # If we exhausted models, raise last error
        raise Exception(last_error or "Groq API request failed")
        
    except Exception as e:
        print(f"Error in groq_chat_completion: {e}")
        raise e
