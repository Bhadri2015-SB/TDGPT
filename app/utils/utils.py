import os
import aiofiles
from app.core.config import IMAGE_OUTPUT_DIR
from app.core.logger import app_logger 

async def summarize_text(text, groq_client, model):
    if not text.strip():
        app_logger.warning("Empty text received for summarization.")
        return "No content to summarize."

    prompt = f"Summarize this content in 1-2 lines:\n{text[:3000]}"
    
    try:
        response = await groq_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        summary = response.choices[0].message.content.strip()
        app_logger.info("Summarization completed successfully.")
        return summary

    except Exception as e:
        app_logger.exception(f"Error during summarization: {e}")
        return "Summary not available due to an error."
