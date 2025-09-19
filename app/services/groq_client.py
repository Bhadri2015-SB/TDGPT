import os
import requests
from typing import Optional
from app.core import config


def chat_complete(system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.3) -> Optional[str]:
    api_key = os.getenv("GROQ_API_KEY")
    model = config.GROQ_MODEL
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content")
    except Exception:
        return None
