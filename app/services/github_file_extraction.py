import os
import re
import base64
import httpx
from fastapi import UploadFile
from io import BytesIO
from dotenv import load_dotenv

from app.core.config import UPLOAD_ROOT, FILE_TYPE_MAP
from app.utils.file_handler import save_file
from app.core.logger import app_logger  

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

GITHUB_API_BASE = "https://api.github.com"
BASE_SAVE_DIR = UPLOAD_ROOT
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "Accept": "application/vnd.github.v3+json"
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"


def parse_github_url(url: str):
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)", url)
    if not match:
        app_logger.error(f"Invalid GitHub URL format: {url}")
        raise ValueError("Invalid GitHub URL format.")
    owner, repo = match.group(1), match.group(2)
    app_logger.info(f"Parsed GitHub URL: owner={owner}, repo={repo}")
    return owner, repo


async def fetch_contents(client, owner, repo, path=""):
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    app_logger.debug(f"Fetching contents from: {url}")
    response = await client.get(url)

    if response.status_code != 200:
        app_logger.error(f"GitHub API error ({url}): {response.status_code} - {response.text}")
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
    
    app_logger.info(f"Fetched {len(files)} files from repo={repo}, path='{path}'")
    return files


async def download_and_save_files(client, owner, repo, file_paths):
    saved_files = []

    for path in file_paths:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        response = await client.get(url)
        if response.status_code != 200:
            app_logger.warning(f"Skipping file (fetch error): {path}")
            continue

        data = response.json()
        if data.get("encoding") == "base64":
            try:
                content = base64.b64decode(data["content"])
                file_obj = BytesIO(content)
                upload_file = UploadFile(filename=os.path.basename(path), file=file_obj)

                saved_path = await save_file(repo, upload_file)  # ✅ Await here if save_file is async
                saved_files.append(saved_path)
                app_logger.info(f"Saved file: {saved_path}")
            except Exception as e:
                app_logger.exception(f"Error decoding/saving file: {path} - {e}")
                continue
        else:
            app_logger.warning(f"Unsupported encoding for file: {path}")

    app_logger.info(f"Total files saved: {len(saved_files)}")
    return saved_files


async def get_repo_files(repo_url: str):
    try:
        owner, repo = parse_github_url(repo_url)
        async with httpx.AsyncClient(headers=HEADERS) as client:
            all_files = await fetch_contents(client, owner, repo)
            saved_txt_files = await download_and_save_files(client, owner, repo, all_files)

        summary = {
            "repository": repo_url,
            "total_files": len(all_files),
            "total_txt_files": len(saved_txt_files),
            "saved_txt_files": saved_txt_files
        }
        app_logger.info(f"Completed processing repository: {repo_url}")
        return summary

    except Exception as e:
        app_logger.exception(f"Failed to process repository: {repo_url} - {e}")
        return {
            "repository": repo_url,
            "error": str(e)
        }
