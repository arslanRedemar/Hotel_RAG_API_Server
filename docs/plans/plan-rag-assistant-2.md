# Plan: RAG Assistant — DB 스키마 / API 상세 설계

> **상위 문서**: [plan-rag-assistant.md](./plan-rag-assistant.md)
> **내용**: 인증 시스템, 문서 버전 관리, DB 스키마, API 전체 명세

---

## 1. DB 스키마 전체 설계

### 신규 테이블 DDL

```sql
-- 부서 마스터
CREATE TABLE departments (
    id          VARCHAR(50)  PRIMARY KEY,        -- 'front_office', 'housekeeping' 등
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- 사용자
CREATE TABLE users (
    id              INT          PRIMARY KEY AUTO_INCREMENT,
    email           VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(100) NOT NULL,
    role            ENUM('admin', 'manager', 'staff') NOT NULL DEFAULT 'staff',
    department_id   VARCHAR(50)  REFERENCES departments(id),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    login_fail_count INT         NOT NULL DEFAULT 0,
    locked_until    DATETIME     NULL,
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_department (department_id)
);

-- 문서 마스터 (원본 파일)
CREATE TABLE documents (
    id              VARCHAR(36)  PRIMARY KEY,         -- UUID
    title           VARCHAR(255) NOT NULL,
    department_id   VARCHAR(50)  REFERENCES departments(id),
    current_version VARCHAR(20)  NOT NULL DEFAULT '1.0',
    status          ENUM('active', 'archived') NOT NULL DEFAULT 'active',
    tags            JSON,                              -- ["체크인", "프런트"]
    created_by      INT          REFERENCES users(id),
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_department (department_id),
    INDEX idx_status (status)
);

-- 문서 버전 이력
CREATE TABLE document_versions (
    id              INT          PRIMARY KEY AUTO_INCREMENT,
    document_id     VARCHAR(36)  NOT NULL REFERENCES documents(id),
    version         VARCHAR(20)  NOT NULL,             -- '1.0', '2.1'
    file_path       VARCHAR(500) NOT NULL,             -- 스토리지 경로
    file_name       VARCHAR(255) NOT NULL,
    file_size_bytes BIGINT,
    file_type       ENUM('pdf', 'txt', 'docx') NOT NULL,
    chroma_ids      JSON,                              -- 이 버전의 ChromaDB chunk ID 목록
    indexed_chunks  INT,
    index_duration_ms INT,
    change_summary  TEXT,                              -- 변경 내용 요약
    uploaded_by     INT          REFERENCES users(id),
    uploaded_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_doc_version (document_id, version),
    INDEX idx_document_id (document_id)
);

-- 부서별 문서 접근 권한 (문서가 복수 부서에 공유될 때)
CREATE TABLE document_access (
    document_id   VARCHAR(36) NOT NULL REFERENCES documents(id),
    department_id VARCHAR(50) NOT NULL REFERENCES departments(id),
    granted_by    INT         REFERENCES users(id),
    granted_at    DATETIME    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id, department_id)
);

-- SOP 확인(Acknowledge) 이력
CREATE TABLE sop_acknowledgements (
    id          INT       PRIMARY KEY AUTO_INCREMENT,
    document_id VARCHAR(36) NOT NULL REFERENCES documents(id),
    version     VARCHAR(20) NOT NULL,
    user_id     INT         NOT NULL REFERENCES users(id),
    acked_at    DATETIME    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ack (document_id, version, user_id)
);

-- 기존 chat_sessions, chat_messages 유지
-- chat_sessions에 user_id 컬럼 추가
ALTER TABLE chat_sessions
    ADD COLUMN user_id INT REFERENCES users(id),
    ADD INDEX idx_user_id (user_id);
```

### 기본 데이터 (Seed)

```sql
INSERT INTO departments (id, name) VALUES
('front_office',      '프런트 오피스'),
('housekeeping',      '하우스키핑'),
('fb',               '식음료(F&B)'),
('engineering',       '시설 관리'),
('hr',               '인사 & 교육'),
('revenue',           '수익 관리'),
('procurement',       '구매 & 재무'),
('quality',          '품질 & 컴플라이언스'),
('all',              '전체 공통');
```

---

## 2. 인증 시스템 설계

### 2-1. JWT 토큰 구조

```python
# app/auth/jwt.py

from datetime import datetime, timedelta
from jose import JWTError, jwt
from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1시간 (SYS-F02)

def create_access_token(data: dict) -> str:
    """
    payload 구조:
    {
        "sub": "user@hotel.com",   # 이메일
        "user_id": 1,
        "role": "manager",
        "department": "front_office",
        "exp": <timestamp>
    }
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않습니다")
```

### 2-2. 인증 의존성

```python
# app/auth/dependencies.py

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.auth.jwt import decode_token
from app.database.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    payload = decode_token(token)
    user = db.query(User).filter_by(email=payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="인증 실패")
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")
    return current_user

def require_manager(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="매니저 이상 권한이 필요합니다")
    return current_user
```

### 2-3. 인증 API 엔드포인트

```
POST /api/v1/auth/login
  Body:  { email, password }
  Response: { access_token, token_type, user: { id, email, full_name, role, department } }

POST /api/v1/auth/register        (Admin 전용)
  Body:  { email, password, full_name, role, department_id }
  Response: { user }

GET  /api/v1/auth/me
  Header: Authorization: Bearer <token>
  Response: { id, email, full_name, role, department }

POST /api/v1/auth/change-password
  Body:  { current_password, new_password }

GET  /api/v1/users                (Admin 전용)
GET  /api/v1/users/{user_id}
PUT  /api/v1/users/{user_id}      (Admin 전용)
DELETE /api/v1/users/{user_id}    (Admin 전용)
```

### 2-4. 계정 잠금 로직

```python
# app/database/crud.py

def handle_login_attempt(db: Session, user: User, success: bool):
    if success:
        user.login_fail_count = 0
        user.locked_until = None
    else:
        user.login_fail_count += 1
        if user.login_fail_count >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=30)
    db.commit()

def is_account_locked(user: User) -> bool:
    if user.locked_until and user.locked_until > datetime.utcnow():
        return True
    return False
```

---

## 3. 문서 버전 관리

### 3-1. 문서 API 전체 명세

```
# 문서 목록 조회 (부서 필터 자동 적용)
GET /api/v1/documents
  Query: department?, status?, tags?, page, page_size
  Response: { items: [Document], total, page, page_size }

# 문서 단건 조회
GET /api/v1/documents/{doc_id}
  Response: Document + versions[]

# 문서 신규 등록 (파일 업로드 + 인덱싱)
POST /api/v1/documents
  Content-Type: multipart/form-data
  Body: file, title, department_id, tags, change_summary
  Response: { document_id, version, indexed_chunks, duration_ms }

# 신규 버전 업로드
POST /api/v1/documents/{doc_id}/versions
  Content-Type: multipart/form-data
  Body: file, change_summary
  Response: { version, indexed_chunks, duration_ms }

# 버전 목록 조회
GET /api/v1/documents/{doc_id}/versions
  Response: [DocumentVersion]

# 특정 버전 아카이브 (검색 제외)
PATCH /api/v1/documents/{doc_id}/versions/{version}/archive

# 문서 아카이브 (전체 비활성화)
DELETE /api/v1/documents/{doc_id}

# SOP 확인(Acknowledge)
POST /api/v1/documents/{doc_id}/acknowledge
  Body: { version }

# 부서 확인율 조회 (Manager+)
GET /api/v1/documents/{doc_id}/acknowledgement-stats
  Response: { version, total_staff, acknowledged, rate_pct }
```

### 3-2. 버전 전환 로직 (재인덱싱)

```python
# app/rag/ingest.py

def replace_document_version(
    document_id: str,
    old_chroma_ids: list[str],
    new_file_path: str,
    metadata: dict
) -> tuple[list[str], int]:
    """
    1. 기존 버전의 ChromaDB 청크를 ID 목록으로 삭제
    2. 새 파일을 파싱 → 청크 분할 → 메타데이터 부착
    3. ChromaDB에 새 청크 추가
    4. 새 청크 ID 목록 반환
    """
    vector_store = get_vector_store()

    # Step 1: 기존 청크 삭제
    if old_chroma_ids:
        vector_store._collection.delete(ids=old_chroma_ids)

    # Step 2: 새 문서 파싱
    documents = load_document(new_file_path)  # PDF/DOCX/TXT 통합 로더

    # Step 3: 청크 분할 + 메타데이터 부착
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap
    )
    chunks = splitter.split_documents(documents)

    # 각 청크에 메타데이터 부착
    chunk_ids = []
    for i, chunk in enumerate(chunks):
        chunk_id = f"{document_id}-v{metadata['version']}-{i}"
        chunk.metadata.update({**metadata, "chunk_index": i})
        chunk_ids.append(chunk_id)

    # Step 4: ChromaDB 저장
    vector_store.add_documents(chunks, ids=chunk_ids)

    return chunk_ids, len(chunks)
```

---

## 4. RAG 파이프라인 권한 필터 상세

### 4-1. 부서 필터가 적용된 Retriever

```python
# app/rag/graph.py

def build_user_retriever(user: User):
    """사용자의 접근 가능 부서에 따라 필터된 retriever 반환"""

    if user.role == "admin":
        # Admin은 모든 문서 접근
        filter_condition = None
    else:
        # Manager/Staff는 소속 부서 + 공통(all) 문서만
        allowed = [user.department_id, "all"]
        filter_condition = {"department": {"$in": allowed}}

    return get_vector_store().as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": settings.top_k_results,
            "filter": filter_condition
        }
    )
```

### 4-2. 개선된 RAG Graph

```python
# app/rag/graph.py

class RAGState(TypedDict):
    messages: Annotated[list, add_messages]
    context: list[Document]
    user_id: int            # 추가: 사용자 식별
    department: str         # 추가: 부서 필터용

def _build_user_graph(user: User):
    """사용자별 권한이 적용된 그래프 생성 (RAG-F16, RAG-F17: LLMRouter 적용)"""
    from app.core.llm_router import llm_router, TaskTier
    retriever = build_user_retriever(user)

    def retrieve(state: RAGState) -> dict:
        question = state["messages"][-1].content
        docs = retriever.invoke(question)
        return {"context": docs}

    def generate(state: RAGState) -> dict:
        question = state["messages"][-1].content
        docs = state["context"]

        # RAG-F17: 쿼리 복잡도로 LLM Tier 결정
        # 단일 소스 + 짧은 쿼리 → 로컬 LLM, 다중 소스 → 클라우드
        tier = TaskTier.LOCAL_FIRST if (len(docs) <= 1 and len(question) < 50) else TaskTier.CLOUD_FIRST
        llm = llm_router.get_llm(tier)

        context_text = "\n\n---\n\n".join(
            f"[출처: {doc.metadata.get('source', '알 수 없음')} "
            f"p.{doc.metadata.get('page', '?')}]\n{doc.page_content}"
            for doc in docs
        )
        system_msg = SystemMessage(content=SYSTEM_PROMPT.format(context=context_text))
        response = llm.invoke([system_msg] + list(state["messages"]))
        return {"messages": [response], "_llm_tier": tier.name}

    graph = StateGraph(RAGState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile(checkpointer=_memory)
```

---

## 5. 인덱싱 API 개선 (RAG-F04)

```python
# app/api/routes/ingest.py

import time

@router.post("", response_model=IngestResponse)
async def ingest(
    request: IngestRequest = IngestRequest(),
    current_user: User = Depends(require_manager)  # 인증 추가
):
    start = time.perf_counter()

    try:
        count = ingest_documents(collection_name=request.collection_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return IngestResponse(
        message="문서 인제스트 완료",
        doc_count=count,
        duration_ms=elapsed_ms    # 추가
    )
```

```python
# app/models/schemas.py 수정

class IngestResponse(BaseModel):
    message: str
    doc_count: int
    duration_ms: int    # 추가
```

---

## 6. Pydantic 스키마 전체 개정안

```python
# app/models/schemas.py

# === 인증 ===
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"

class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    department_id: Optional[str]
    class Config: from_attributes = True

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: Literal["admin", "manager", "staff"] = "staff"
    department_id: Optional[str] = None

# === 채팅 ===
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class SourceDocument(BaseModel):
    source: str
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_preview: str  # 첫 150자

class ChatResponse(BaseModel):
    answer: str
    source_documents: list[SourceDocument] = []
    session_id: str

# === 문서 관리 ===
class DocumentVersionOut(BaseModel):
    version: str
    file_name: str
    file_type: str
    indexed_chunks: Optional[int]
    change_summary: Optional[str]
    uploaded_by: Optional[str]
    uploaded_at: datetime
    class Config: from_attributes = True

class DocumentOut(BaseModel):
    id: str
    title: str
    department_id: Optional[str]
    current_version: str
    status: str
    tags: Optional[list[str]]
    created_at: datetime
    versions: list[DocumentVersionOut] = []
    class Config: from_attributes = True

class DocumentCreate(BaseModel):
    title: str
    department_id: str
    tags: list[str] = []
    change_summary: Optional[str] = None

# === 인덱싱 ===
class IngestResponse(BaseModel):
    message: str
    doc_count: int
    duration_ms: int

# === 이력 ===
class MessageOut(BaseModel):
    role: str
    content: str
    sources: Optional[list[str]] = None
    created_at: datetime
    class Config: from_attributes = True

class HistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageOut]
```

---

## 7. 환경 변수 추가 (.env)

```bash
# 기존 변수 외 추가 필요 항목

# JWT 설정
SECRET_KEY=your-256-bit-secret-key-here   # openssl rand -hex 32 로 생성
ACCESS_TOKEN_EXPIRE_MINUTES=60

# 파일 스토리지
FILE_STORAGE_PATH=./data/uploads          # 원본 문서 저장 경로

# 이메일 알림 (Phase 3+)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@hotel.com
SMTP_PASSWORD=your-smtp-password
```
