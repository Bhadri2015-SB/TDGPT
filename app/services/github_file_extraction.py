import os
import re
import httpx
from fastapi import UploadFile
from io import BytesIO

from app.core.config import UPLOAD_ROOT, FILE_TYPE_MAP
from app.utils.file_handler import save_file

BASE_SAVE_DIR = UPLOAD_ROOT

GITHUB_API_BASE = "https://api.github.com"

from dotenv import load_dotenv
load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

HEADERS = {
    "Accept": "application/vnd.github.v3+json"
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def parse_github_url(url: str):
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)", url)
    if not match:
        raise ValueError("Invalid GitHub URL format.")
    return match.group(1), match.group(2)

async def fetch_contents(client, owner, repo, path=""):
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    response = await client.get(url)
    if response.status_code != 200:
        raise ValueError(f"GitHub API error: {response.status_code} - {response.text}")
    
    data = response.json()
    files = []

    if isinstance(data, dict) and data.get("type") == "file":
        files.append(data["path"])
    else:
        for item in data:
            if item["type"] == "file":
                files.append(item["path"])
            elif item["type"] == "dir":
                nested_files = await fetch_contents(client, owner, repo, item["path"])
                files.extend(nested_files)
    
    return files

async def download_and_save_files(client, owner, repo, file_paths):
    saved_files = []

    for path in file_paths:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        response = await client.get(url)
        if response.status_code != 200:
            continue

        data = response.json()
        if data.get("encoding") == "base64":
            import base64
            content = base64.b64decode(data["content"])

            # Convert to UploadFile-like object
            file_obj = BytesIO(content)
            upload_file = UploadFile(filename=os.path.basename(path), file=file_obj)

            # Use your existing save_file function
            saved_path = save_file(repo, upload_file)
            saved_files.append(saved_path)

    return saved_files



async def get_repo_files(repo_url: str):
    owner, repo = parse_github_url(repo_url)
    async with httpx.AsyncClient(headers=HEADERS) as client:
        all_files = await fetch_contents(client, owner, repo)
        saved_txt_files = await download_and_save_files(client, owner, repo, all_files)

    return {
        "repository": repo_url,
        "total_files": len(all_files),
        "total_txt_files": len(saved_txt_files),
        "saved_txt_files": saved_txt_files
    }
