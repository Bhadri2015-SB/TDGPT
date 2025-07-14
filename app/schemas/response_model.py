from pydantic import BaseModel, EmailStr
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

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

class QueryRequest(BaseModel):
    query: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    new_password: str
    email: EmailStr

class VerifyOTPRequest(BaseModel):
    otp: str
    email: EmailStr