import os
import aiofiles
from typing import List, Dict, Optional
import requests
from app.core.config import IMAGE_OUTPUT_DIR
from app.core import config




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
       
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
       
        model_sequence = [model or config.GROQ_MODEL]
        for fb in config.GROQ_MODEL_FALLBACKS:
            if fb not in model_sequence:
                model_sequence.append(fb)
        
       
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        
     
        chat_messages = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        
        chat_messages.extend(messages)
        
        last_error = None
        for mdl in model_sequence:
            
            payload = {
                "model": mdl,
                "messages": chat_messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
          
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload
            )
           
            if response.status_code != 200:
                last_error = f"API request failed with status {response.status_code}: {response.text}"
               
                try:
                    data = response.json()
                    msg = str(data)
                except Exception:
                    msg = response.text
                if "model_decommissioned" in msg or "decommissioned" in msg or response.status_code in (400, 404):
                    continue
            
                break
          
            result = response.json()
         
            if "choices" in result and len(result.get("choices", [])) > 0:
                message_obj = result["choices"][0].get("message", {})
                content = message_obj.get("content")
                if content:
                    return content
          
            last_error = "Unexpected response structure from Groq API"
            continue

       
        raise Exception(last_error or "Groq API request failed")
        
    except Exception as e:
        print(f"Error in groq_chat_completion: {e}")
        raise e
