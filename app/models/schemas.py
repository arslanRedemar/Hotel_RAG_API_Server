from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = []
    session_id: Optional[str] = None


class IngestRequest(BaseModel):
    collection_name: str = "hotel_docs"


class IngestResponse(BaseModel):
    message: str
    doc_count: int
