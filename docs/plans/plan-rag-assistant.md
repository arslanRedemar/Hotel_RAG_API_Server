# Plan: RAG Assistant 구현 계획

> **요구사항 참조**: [rag_assistant.md](../requirements/rag_assistant.md)
> **우선순위**: P0 (최우선)
> **관련 하위 문서**:
> - [plan-rag-assistant-2.md](./plan-rag-assistant-2.md) — DB 스키마 / API 상세 설계
> - [plan-rag-assistant-3.md](./plan-rag-assistant-3.md) — 프런트엔드 구현

---

## 1. 현재 구현 상태 분석

### 구현 완료
| 항목 | 파일 | 상태 |
|------|------|------|
| 기본 RAG 파이프라인 | `app/rag/graph.py` | ✅ 완료 |
| 문서 인덱싱 (PDF/TXT) | `app/rag/ingest.py` | ✅ 완료 |
| ChromaDB 벡터 저장소 | `app/rag/vector_store.py` | ✅ 완료 |
| 채팅 API | `app/api/routes/chat.py` | ✅ 완료 |
| 대화 이력 저장 (MySQL) | `app/database/crud.py` | ✅ 완료 |
| LangGraph 세션 관리 | `app/rag/graph.py` | ✅ 완료 |

### 미구현 (요구사항 Gap)
| 요구사항 ID | 내용 | 우선순위 |
|------------|------|---------|
| RAG-F01 | DOCX 형식 지원 | P0 |
| RAG-F02 | 업로드 시 메타데이터(부서/버전) 저장 | P0 |
| RAG-F03 | 문서 버전 교체 기능 | P1 |
| RAG-F04 | 인덱싱 소요 시간 반환 | P1 |
| RAG-F11 | 출처 문서명 + 섹션 정보 반환 | P0 |
| RAG-F13 | Hallucination 방지 (No-answer 처리) | P0 |
| RAG-F20~22 | 부서별 접근 권한 | P1 |
| RAG-F30~32 | 문서 버전 관리 | P1~P2 |
| SYS-F01~05 | JWT 인증, 역할 기반 권한 | P0 |

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                     Next.js Frontend                     │
│  [채팅 UI]  [문서 관리] [세션 이력] [관리자 대시보드]      │
└────────────────────────┬────────────────────────────────┘
                         │ HTTPS / REST
┌────────────────────────▼────────────────────────────────┐
│                   FastAPI Backend                         │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  /auth   │  │  /chat   │  │ /ingest  │  │/history │ │
│  │  /users  │  │          │  │/documents│  │         │ │
│  └──────────┘  └────┬─────┘  └────┬─────┘  └─────────┘ │
│                     │             │                       │
│  ┌──────────────────▼─────────────▼──────────────────┐  │
│  │              RAG Pipeline (LangGraph)               │  │
│  │   [retrieve] → [access_filter] → [generate]        │  │
│  └──────────────────┬─────────────────────────────────┘  │
│                     │                                     │
│  ┌──────────────────▼───────────────────────────────┐    │
│  │  ChromaDB (벡터 저장소)                            │    │
│  │  Collection per department or metadata filter     │    │
│  └───────────────────────────────────────────────────┘    │
└─────────────────────────────────┬───────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                        │
   ┌──────▼──────┐      ┌────────▼────────┐    ┌─────────▼──────┐
   │  MySQL DB   │      │  File Storage   │    │  OpenAI API    │
   │ - users     │      │  (로컬 or S3)   │    │ - Embeddings   │
   │ - sessions  │      │  - 원본 문서    │    │ - GPT-4o-mini  │
   │ - messages  │      │  - 버전 이력    │    └────────────────┘
   │ - documents │      └─────────────────┘
   │ - doc_versions│
   └─────────────┘
```

---

## 3. 구현 단계 (Phases)

### Phase 1 — 기반 강화 (P0 요구사항)
> 예상 작업량: 3~4일

#### 1-1. DOCX 지원 추가 (RAG-F01)
**파일**: `app/rag/ingest.py`

현재 PDF + TXT만 지원. `python-docx` 라이브러리를 추가하고 DOCX 로더를 연결.

```python
# requirements.txt 추가
python-docx>=1.1.0
langchain-community>=0.3.7  # Docx2txtLoader 포함

# ingest.py 수정 포인트
from langchain_community.document_loaders import Docx2txtLoader

for docx_file in docs_path.glob("**/*.docx"):
    loader = Docx2txtLoader(str(docx_file))
    documents.extend(loader.load())
```

#### 1-2. 메타데이터 저장 구조 개선 (RAG-F02)
**파일**: `app/database/models.py`, `app/rag/ingest.py`

ChromaDB에 저장되는 메타데이터에 부서, 버전, 업로드자 정보를 포함.

```python
# ChromaDB 메타데이터 구조 (청크 단위)
{
  "source": "checkin_sop.pdf",
  "source_id": "doc-001",          # Document 테이블 FK
  "department": "front_office",
  "version": "2.1",
  "uploaded_by": "admin@hotel.com",
  "uploaded_at": "2026-03-27T09:00:00",
  "page": 1,                        # PDF 페이지 번호
  "chunk_index": 3
}
```

#### 1-3. Hallucination 방지 프롬프트 강화 (RAG-F13)
**파일**: `app/rag/graph.py`

현재 시스템 프롬프트에 명확한 No-answer 지시 추가.

```python
SYSTEM_PROMPT = """당신은 호텔 운영 전문 AI 어시스턴트입니다.

[중요 규칙]
1. 반드시 아래 제공된 컨텍스트 문서만을 근거로 답변하세요.
2. 컨텍스트에 없는 정보는 절대 생성하지 마세요.
3. 컨텍스트에서 답을 찾을 수 없다면 정확히 이렇게 답하세요:
   "제공된 문서에서 해당 정보를 찾을 수 없습니다. 관련 부서 담당자에게 문의해 주세요."
4. 답변 말미에 참고한 문서명을 반드시 언급하세요.

[컨텍스트 문서]
{context}
"""
```

#### 1-4. 출처 섹션 정보 반환 강화 (RAG-F11)
**파일**: `app/api/routes/chat.py`, `app/models/schemas.py`

현재 소스 파일명만 반환. 페이지, 섹션까지 반환하도록 개선.

```python
# schemas.py 수정
class SourceDocument(BaseModel):
    source: str          # 파일명
    page: Optional[int]  # 페이지 번호
    section: Optional[str]  # 섹션/헤더
    chunk_preview: str   # 매칭된 청크 미리보기 (첫 100자)

class ChatResponse(BaseModel):
    answer: str
    source_documents: list[SourceDocument] = []  # 기존 sources → 상세화
    session_id: Optional[str] = None
```

#### 1-5. 로컬 임베딩 및 LLM 쿼리 라우팅 (RAG-F16, RAG-F17)
**파일**: `app/rag/ingest.py`, `app/rag/graph.py`

임베딩은 기본값 로컬(Ollama), 단순 단일 청크 쿼리는 로컬 LLM으로 처리. 복합 쿼리만 클라우드로 라우팅.

```python
# app/rag/ingest.py — 임베딩 프로바이더 전환 (RAG-F16)
from app.core.embedding_router import get_embeddings

def ingest_documents(docs_path: str):
    embeddings = get_embeddings()  # EMBEDDING_PROVIDER 환경변수로 결정
    vectorstore = Chroma(
        persist_directory=settings.chroma_persist_dir,
        embedding_function=embeddings,
    )
    # ... 기존 로직
```

```python
# app/rag/graph.py — 쿼리 복잡도 기반 LLM 라우팅 (RAG-F17)
from app.core.llm_router import llm_router, TaskTier

def classify_query_complexity(query: str, retrieved_docs: list) -> TaskTier:
    """
    단순 쿼리(단일 소스, 단답형) → Tier 2 로컬 LLM
    복합 쿼리(다수 소스 통합, 추론 필요) → Tier 3 클라우드
    """
    if len(retrieved_docs) <= 1 and len(query) < 50:
        return TaskTier.LOCAL_FIRST  # 로컬 LLM
    return TaskTier.CLOUD_FIRST      # 클라우드 LLM

def rag_node_generate(state: dict) -> dict:
    query = state["question"]
    docs = state["retrieved_docs"]

    tier = classify_query_complexity(query, docs)
    llm = llm_router.get_llm(tier)

    context = "\n\n".join(d.page_content for d in docs)
    prompt = SYSTEM_PROMPT.format(context=context)
    response = llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=query),
    ])
    return {**state, "answer": response.content, "_llm_tier": tier.name}
```

---

### Phase 2 — 인증 및 권한 (SYS-F01~05 + RAG-F20~22)
> 예상 작업량: 4~5일
> 상세 설계: [plan-rag-assistant-2.md](./plan-rag-assistant-2.md#2-인증-시스템-설계)

#### 2-1. JWT 인증 레이어 추가
새 파일 생성:
- `app/auth/jwt.py` — 토큰 생성/검증 로직
- `app/auth/dependencies.py` — FastAPI Depends 함수
- `app/api/routes/auth.py` — 로그인/회원가입 엔드포인트

#### 2-2. 사용자/역할 DB 모델
`app/database/models.py`에 `User`, `Role`, `Department` 엔티티 추가.

#### 2-3. RAG 파이프라인 권한 필터
ChromaDB 쿼리 시 `where` 조건으로 부서 필터 적용:
```python
retriever = vector_store.as_retriever(
    search_kwargs={
        "k": 5,
        "filter": {"department": {"$in": user.allowed_departments}}
    }
)
```

---

### Phase 3 — 문서 버전 관리 (RAG-F03, F30~32)
> 예상 작업량: 3일
> 상세 설계: [plan-rag-assistant-2.md](./plan-rag-assistant-2.md#3-문서-버전-관리)

#### 3-1. 문서 관리 API
- `POST /api/v1/documents` — 새 문서 등록
- `POST /api/v1/documents/{doc_id}/versions` — 새 버전 업로드
- `GET /api/v1/documents` — 문서 목록 조회
- `DELETE /api/v1/documents/{doc_id}/versions/{version}` — 버전 아카이브

#### 3-2. 버전 전환 시 ChromaDB 재인덱싱
기존 버전의 청크를 `source_id`로 식별해 삭제 후 새 버전 청크 추가.

---

### Phase 4 — 프런트엔드 채팅 UI
> 예상 작업량: 5~7일
> 상세 설계: [plan-rag-assistant-3.md](./plan-rag-assistant-3.md)

- 채팅 인터페이스 (실시간 스트리밍 지원)
- 문서 관리 페이지
- 세션 이력 사이드바

---

## 4. 파일 구조 변경 계획

```
app/
├── auth/                          # 신규 추가
│   ├── __init__.py
│   ├── jwt.py                     # JWT 토큰 유틸리티
│   ├── dependencies.py            # get_current_user() Depends
│   └── password.py                # bcrypt 해싱
│
├── api/
│   └── routes/
│       ├── auth.py                # 신규: POST /auth/login, /auth/register
│       ├── documents.py           # 신규: 문서 CRUD API
│       ├── chat.py                # 수정: 인증 + 상세 소스 반환
│       ├── ingest.py              # 수정: 메타데이터 + 인덱싱 시간
│       └── history.py             # 유지
│
├── database/
│   └── models.py                  # 수정: User, Document, DocumentVersion 추가
│
├── rag/
│   ├── graph.py                   # 수정: 프롬프트 강화, 권한 필터
│   ├── ingest.py                  # 수정: DOCX 지원, 메타데이터 강화
│   └── vector_store.py            # 수정: 필터링 지원 메서드 추가
│
└── models/
    └── schemas.py                 # 수정: SourceDocument, 인증 DTO 추가
```

---

## 5. 의존성 추가

```
# requirements.txt 추가 항목
python-docx>=1.1.0          # DOCX 파싱
python-jose[cryptography]>=3.3.0  # JWT
passlib[bcrypt]>=1.7.4     # 비밀번호 해싱
python-multipart>=0.0.9    # 파일 업로드
```

---

## 6. 테스트 전략

| 테스트 종류 | 대상 | 방법 |
|-----------|------|------|
| 단위 테스트 | `ingest.py` DOCX 파싱 | pytest + 샘플 DOCX |
| 단위 테스트 | JWT 생성/검증 | pytest |
| 단위 테스트 | Hallucination 방지 | 관련 문서 없는 질문 시 No-answer 응답 확인 |
| 통합 테스트 | 부서 필터 | 다른 부서 문서가 검색 결과에서 제외되는지 확인 |
| 통합 테스트 | 버전 교체 | 구버전 청크 삭제 + 신버전 청크 반환 확인 |
| 성능 테스트 | 동시 50 사용자 | Locust로 채팅 API 부하 테스트 |

---

## 7. 위험 요소 및 대응

| 위험 | 가능성 | 대응 |
|------|--------|------|
| ChromaDB 필터 성능 저하 (대량 문서) | 중간 | 컬렉션을 부서별로 분리하는 구조로 전환 고려 |
| OpenAI API 레이트 리밋 | 중간 | 지수 백오프 재시도 + 토큰 사용량 모니터링 |
| DOCX 복잡한 레이아웃 파싱 실패 | 낮음 | 파싱 실패 시 원본 업로드 + 수동 처리 안내 |
| 기존 ChromaDB 데이터 마이그레이션 | 중간 | 메타데이터 없는 기존 청크는 재인덱싱 스크립트 제공 |

---

## 8. 구현 우선순위 체크리스트

### Phase 1 (즉시 시작)
- [ ] `requirements.txt`에 `python-docx`, `python-jose`, `passlib` 추가
- [ ] `ingest.py` DOCX 로더 추가
- [ ] `graph.py` 시스템 프롬프트 Hallucination 방지 강화
- [ ] `schemas.py` `SourceDocument` 모델 추가
- [ ] `chat.py` 소스 섹션 정보 반환 개선
- [ ] 인덱싱 소요 시간 측정 및 반환 (`time.perf_counter`)

### Phase 2 (Phase 1 완료 후)
- [ ] `app/auth/` 모듈 생성
- [ ] `User`, `Department` DB 모델 추가 및 마이그레이션
- [ ] `/api/v1/auth/login`, `/register` 엔드포인트 구현
- [ ] 기존 API에 `Depends(get_current_user)` 적용
- [ ] ChromaDB 부서 필터 적용

### Phase 3 (Phase 2 완료 후)
- [ ] `Document`, `DocumentVersion` DB 모델 추가
- [ ] `/api/v1/documents` CRUD 엔드포인트 구현
- [ ] 버전 전환 시 ChromaDB 재인덱싱 로직
- [ ] 변경 알림 발송 연동

### Phase 4 (병행 가능)
- [ ] Next.js 채팅 UI 구현
- [ ] 문서 관리 페이지 구현
- [ ] 세션 이력 사이드바 구현
