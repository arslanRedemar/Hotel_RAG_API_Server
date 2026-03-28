from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Optional


class SourceDocument(BaseModel):
    """RAG-F11: 출처 문서 상세 정보"""
    source: str
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_preview: str = ""
    doc_type: Optional[str] = None
    department_id: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    department_ids: Optional[list[int]] = None  # RAG-F20: 부서 필터


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = []                       # 하위 호환
    source_documents: list[SourceDocument] = []   # RAG-F11: 상세 출처
    session_id: Optional[str] = None


class IngestRequest(BaseModel):
    collection_name: str = "hotel_docs"


class IngestResponse(BaseModel):
    message: str
    doc_count: int


class MessageOut(BaseModel):
    role: str
    content: str
    sources: Optional[list[str]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageOut]


# ── SOP 스키마 ───────────────────────────────────────────────

class SOPStep(BaseModel):
    step_no: int
    action: str
    responsible: Optional[str] = None
    duration_min: Optional[int] = None
    notes: Optional[str] = None


class SOPChecklistItem(BaseModel):
    text: str
    required: bool = True


class SOPUpdateRequest(BaseModel):
    title: Optional[str] = None
    steps: Optional[list[SOPStep]] = None
    checklist_items: Optional[list[SOPChecklistItem]] = None
    cautions: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    review_required: Optional[bool] = None


class SOPOut(BaseModel):
    id: str
    title: str
    department_id: Optional[int] = None
    version: str
    status: str
    steps: Optional[list] = None
    checklist_items: Optional[list] = None
    cautions: Optional[list] = None
    tags: Optional[list] = None
    review_required: bool
    extraction_confidence: Optional[float] = None
    ocr_confidence: Optional[float] = None
    created_by: Optional[int] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SOPExtractResponse(BaseModel):
    sop_id: str
    title: str
    review_required: bool
    extraction_confidence: Optional[float] = None
    ocr_confidence: Optional[float] = None
    status: str


class AcknowledgeStatsOut(BaseModel):
    total_staff: int
    acknowledged: int
    pending: int
    completion_rate: float


# ── Document 스키마 ──────────────────────────────────────────

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    file_type: str
    storage_key: str
    department_id: Optional[int] = None
    uploaded_by: Optional[int] = None
    version: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    id: int
    title: str
    file_type: str
    chunk_count: int
    elapsed_ms: int
    department_id: Optional[int] = None
    version: int = 1
