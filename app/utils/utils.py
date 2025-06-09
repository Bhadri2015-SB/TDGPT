import os
import aiofiles
from app.core.config import IMAGE_OUTPUT_DIR

async def save_image(element, pdf_name, page_number, image_count):
    os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)
    image_path = os.path.join(IMAGE_OUTPUT_DIR, f"{pdf_name}_page_{page_number}_img_{image_count}.png")
    image_data = getattr(element, "image", None)
    if image_data and hasattr(image_data, "save"):
        try:
           
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, image_data.save, image_path)
            return image_path
        except Exception as e:
            print(f" Error saving image on page {page_number} image {image_count}: {e}")
    else:
        print(f" No image data found on page {page_number} image {image_count}")
    return None

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

async def save_image_to_folder(image_bytes, filename, has_text):
    folder = "img_summary" if has_text else "img_vision"
    dir_path = os.path.join(IMAGE_OUTPUT_DIR, folder)
    os.makedirs(dir_path, exist_ok=True)
    image_path = os.path.join(dir_path, filename)
    import aiofiles
    async with aiofiles.open(image_path, "wb") as f:
        await f.write(image_bytes)
    return image_path
