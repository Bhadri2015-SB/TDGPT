import os
import json
import asyncio
import aiofiles
from PIL import Image
import torch
from transformers import VisionEncoderDecoderModel, ViTImageProcessor, AutoTokenizer

from app.core.logger import app_logger  


caption_model = VisionEncoderDecoderModel.from_pretrained("nlpconnect/vit-gpt2-image-captioning")
feature_extractor = ViTImageProcessor.from_pretrained("nlpconnect/vit-gpt2-image-captioning")
tokenizer = AutoTokenizer.from_pretrained("nlpconnect/vit-gpt2-image-captioning")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
caption_model.to(device)

app_logger.info(f"Image captioning model loaded on device: {device}")


async def describe_image(image_path):
    """
    Generate a caption/description for a given image using ViT-GPT2.

    Args:
        image_path (str): Path to the image file.

    Returns:
        str: Generated image description.
    """
    loop = asyncio.get_running_loop()
    try:
        app_logger.debug(f"Loading image: {image_path}")
        image = await loop.run_in_executor(None, lambda: Image.open(image_path).convert("RGB"))

        app_logger.debug("Extracting pixel values...")
        pixel_values = feature_extractor(images=image, return_tensors="pt").pixel_values.to(device)

        app_logger.debug("Generating image caption...")
        output_ids = await loop.run_in_executor(
            None, lambda: caption_model.generate(pixel_values, max_length=64, num_beams=1)
        )

        description = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        app_logger.info(f"Generated caption for {os.path.basename(image_path)}: {description}")
        return description

    except Exception as e:
        app_logger.exception(f"Error describing image {image_path}: {e}")
        return "Description unavailable due to error."
