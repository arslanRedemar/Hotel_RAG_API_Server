# Hotel_RAG_API_Server
호텔 데모 어플리케이션 API server

## 기술 스택
- **FastAPI** — REST API 서버
- **LangChain** — RAG 파이프라인
- **ChromaDB** — 벡터 저장소 (로컬 persistent)
- **OpenAI** — LLM (`gpt-4o-mini`) + Embeddings (`text-embedding-3-small`)

## 프로젝트 구조
```
Hotel_RAG_API_Server/
├── main.py                   # FastAPI 앱 진입점
├── requirements.txt
├── .env.example
├── app/
│   ├── api/
│   │   ├── router.py
│   │   └── routes/
│   │       ├── chat.py       # POST /api/v1/chat
│   │       └── ingest.py     # POST /api/v1/ingest
│   ├── core/
│   │   └── config.py         # 환경 변수 설정
│   ├── models/
│   │   └── schemas.py        # Pydantic 스키마
│   └── rag/
│       ├── chain.py          # RAG 체인 (세션별 대화 이력)
│       ├── ingest.py         # 문서 → 벡터 DB 인제스트
│       └── vector_store.py   # ChromaDB 연결
└── data/
    └── docs/                 # 인제스트할 PDF/TXT 파일 위치
```

## 시작하기

### 1. 환경 변수 설정
```bash
cp .env.example .env
# .env 파일에서 OPENAI_API_KEY 입력
```

### 2. 문서 추가
`data/docs/` 디렉토리에 호텔 관련 PDF 또는 TXT 파일을 추가하세요.

### 3. 서버 실행
```bash
.venv\Scripts\python main.py
# 또는
.venv\Scripts\uvicorn main:app --reload
```

### 4. 문서 인제스트 (서버 실행 후)
```bash
curl -X POST http://localhost:8000/api/v1/ingest
```

## API 엔드포인트

| Method | URL | 설명 |
|--------|-----|------|
| GET | `/health` | 헬스 체크 |
| POST | `/api/v1/ingest` | 문서를 벡터 DB에 인제스트 |
| POST | `/api/v1/chat` | RAG 기반 채팅 |

### Chat 예시
```json
POST /api/v1/chat
{
  "message": "체크인 시간이 언제인가요?",
  "session_id": "user-123"
}
```

Swagger UI: http://localhost:8000/docs
