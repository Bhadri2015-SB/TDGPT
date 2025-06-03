from pydantic import BaseModel
from typing import List, Union, Any


class RepoInput(BaseModel):
    repo_url: str

#not used
class PageData(BaseModel):
    text: str
    tables: Union[List[Any], str]
    image: str
    time_taken: str

class PDFExtractedResponse(BaseModel):
    metadata: dict
    page: List[PageData]
    overall_time_taken: str