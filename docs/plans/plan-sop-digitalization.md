# Plan: SOP 자동 구조화 및 디지털화 구현 계획

> **요구사항 참조**: [sop_digitalization.md](../requirements/sop_digitalization.md)
> **우선순위**: P1
> **관련 하위 문서**:
> - [plan-sop-digitalization-2.md](./plan-sop-digitalization-2.md) — OCR 파이프라인 / AI 추출 상세

---

## 1. 현재 상태 및 Gap 분석

### 현재 구현
- 기본 PDF/TXT 파싱 (`app/rag/ingest.py`) — RAG용 청크 분할만 수행
- 구조 추출 없음, 체크리스트 변환 없음, 버전 관리 없음

### 구현 필요 항목
| 요구사항 ID | 내용 | 복잡도 |
|------------|------|--------|
| SOP-F01 | 스캔 PDF OCR 처리 | 높음 |
| SOP-F02 | 텍스트 PDF 직접 추출 | 낮음 (기존 코드 활용) |
| SOP-F10 | AI 기반 단계/주의사항/담당자 추출 | 높음 |
| SOP-F11 | 순서형 단계 구조화 | 중간 |
| SOP-F12 | 체크리스트 변환 | 중간 |
| SOP-F13 | 검토 워크플로 (수동 수정 + 확정) | 중간 |
| SOP-F20 | 웹 에디터 | 높음 |
| SOP-F22 | PDF/체크리스트 Export | 중간 |
| SOP-F30~32 | 버전 이력 + 변경 알림 + Acknowledge | 중간 |

---

## 2. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│                     SOP 디지털화 파이프라인                    │
│                                                              │
│  문서 입력                                                    │
│  ┌──────────┐   ┌───────────┐   ┌──────────────────────┐    │
│  │ 스캔 PDF │──▶│  OCR 처리  │──▶│                      │    │
│  └──────────┘   │(Tesseract │   │  AI 구조 추출 엔진    │    │
│  ┌──────────┐   │ /Google   │   │  (GPT-4o-mini)       │    │
│  │텍스트 PDF│──▶│ Vision)   │──▶│                      │    │
│  └──────────┘   └───────────┘   │  - 단계 추출         │    │
│  ┌──────────┐                   │  - 체크리스트 변환    │    │
│  │  DOCX   │──────────────────▶│  - 담당자/시간 추출   │    │
│  └──────────┘                   │  - 신뢰도 점수        │    │
│                                  └──────────┬───────────┘    │
│                                             │                 │
│                                  ┌──────────▼───────────┐    │
│                                  │   검토 대기 상태     │    │
│                                  │ (review_required=true)│    │
│                                  └──────────┬───────────┘    │
│                                             │ 담당자 검토      │
│                                  ┌──────────▼───────────┐    │
│                                  │   확정 SOP (active)  │    │
│                                  │   ↓                  │    │
│                                  │   MySQL 저장          │    │
│                                  │   RAG 인덱싱 연동     │    │
│                                  └──────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 구현 단계 (Phases)

### Phase 1 — OCR + AI 추출 파이프라인 (SOP-F01~F14)
> 상세: [plan-sop-digitalization-2.md](./plan-sop-digitalization-2.md)

#### 1-1. OCR 처리 모듈

**선택지 평가 (SOP-F06 로컬 우선 전략 반영)**:
| 엔진 | 한국어 정확도 | 비용 | 복잡도 | Tier |
|------|------------|------|--------|------|
| DeepSeek-VL2-Small / GOT-OCR2 (Ollama) | 92~95% | 무료 (로컬) | 중간 | Tier 1 (기본) |
| Tesseract 5.x | 90~93% | 무료 | 낮음 | Tier 1 (폴백) |
| Google Vision API | 98%+ | $1.5/1000페이지 | 낮음 | Tier 3 (저신뢰도 폴백) |

**결정**: 기본값 로컬 비전 모델(DeepSeek-VL2-Small via Ollama), confidence < 0.70이면 Google Vision으로 폴백.
클라우드 폴백 호출은 전체 OCR 요청의 ≤20%를 목표로 함 (SOP-F06).

```python
# app/sop/ocr.py

import pytesseract
from PIL import Image
import pdf2image
from pathlib import Path
import httpx, base64, json

from app.core.config import settings
from app.core.cost_monitor import record_usage

class OCRProcessor:
    """SOP-F06: 로컬 비전 모델 우선, 저신뢰도 시 클라우드 폴백"""

    def __init__(self, engine: str = "local"):
        # engine: "local" | "tesseract" | "google_vision"
        self.engine = engine
        self.confidence_threshold = settings.local_llm_confidence_threshold  # 0.70

    def extract_text_from_scanned_pdf(self, file_path: str) -> list[dict]:
        """
        반환: [{"page": 1, "text": "...", "confidence": 0.95, "engine_used": "local"}, ...]
        """
        images = pdf2image.convert_from_path(file_path, dpi=300)
        results = []

        for page_num, image in enumerate(images, start=1):
            if self.engine == "local":
                text, confidence = self._local_vision_ocr(image)
                engine_used = "local"
                # SOP-F06: 신뢰도 미달 시 클라우드 폴백
                if confidence < self.confidence_threshold:
                    text, confidence = self._google_vision_ocr(image)
                    engine_used = "google_vision"
            elif self.engine == "tesseract":
                text, confidence = self._tesseract_ocr(image)
                engine_used = "tesseract"
            elif self.engine == "google_vision":
                text, confidence = self._google_vision_ocr(image)
                engine_used = "google_vision"
            else:
                text, confidence, engine_used = "", 0.0, "unknown"

            results.append({
                "page": page_num,
                "text": text,
                "confidence": round(confidence, 3),
                "engine_used": engine_used,
            })

        return results

    def _local_vision_ocr(self, image: Image.Image) -> tuple[str, float]:
        """Ollama 로컬 비전 모델(DeepSeek-VL2 / GOT-OCR2) 호출"""
        import io
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        payload = {
            "model": settings.local_ocr_model,  # e.g. "deepseek-vl2"
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": "이 이미지의 텍스트를 정확히 추출해서 원본 형식을 유지하며 반환하세요."},
                    ],
                }
            ],
            "stream": False,
        }
        resp = httpx.post(f"{settings.local_llm_endpoint}/api/chat", json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        # Ollama는 자체 confidence를 제공하지 않으므로 추정값 사용
        confidence = 0.80 if text.strip() else 0.0
        return text, confidence

    def _tesseract_ocr(self, image: Image.Image) -> tuple[str, float]:
        data = pytesseract.image_to_data(image, lang="kor+eng", output_type=pytesseract.Output.DICT)
        text = " ".join(w for w in data["text"] if w.strip())
        conf_values = [c for c in data["conf"] if c != -1]
        confidence = sum(conf_values) / len(conf_values) / 100 if conf_values else 0.0
        return text, confidence

    def _google_vision_ocr(self, image: Image.Image) -> tuple[str, float]:
        # 기존 Google Vision 구현 (SOP-F06 클라우드 폴백)
        record_usage(module="sop_ocr", prompt_tokens=0, completion_tokens=0, model="google_vision")
        raise NotImplementedError("Google Vision OCR 구현 필요")
```

#### 1-2. AI 구조 추출 모듈

```python
# app/sop/extractor.py

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import json

SOP_EXTRACTION_PROMPT = """
당신은 호텔 운영 문서 분석 전문가입니다.
아래 문서 텍스트에서 SOP(표준 운영 절차) 구성 요소를 정확히 추출하세요.

[추출 규칙]
1. steps: 순서가 있는 절차 단계만 추출 (번호나 글머리 기호가 있는 항목)
2. checklist_items: 완료 여부를 체크해야 하는 항목 (체크박스, □, ☐ 표시 등)
3. cautions: 주의사항, 경고, NOTE 섹션
4. responsible: 담당자/역할 언급
5. duration: 소요 시간 언급
6. review_required: 추출 확신도가 70% 미만인 항목이 있으면 true

반드시 아래 JSON 형식으로만 응답하세요:
{
  "title": "문서 제목 추론",
  "steps": [
    {"step_no": 1, "action": "...", "responsible": "...", "duration_min": null, "notes": "..."}
  ],
  "checklist_items": [
    {"text": "...", "required": true}
  ],
  "cautions": ["..."],
  "review_required": false,
  "extraction_confidence": 0.85
}

[문서 텍스트]
{text}
"""

class SOPExtractor:
    """SOP-F15: 로컬 LLM 우선 구조 추출, review_required 항목만 클라우드로 폴백"""

    def __init__(self):
        from app.core.llm_router import llm_router, TaskTier
        self._router = llm_router
        self._tier = TaskTier.LOCAL_FIRST
        self.llm = self._router.get_llm(self._tier)
        self.fallback_llm = self._router.get_fallback(self._tier)

    def extract(self, text: str, max_chars: int = 6000) -> dict:
        """SOP-F15: 로컬 LLM으로 1차 추출, review_required=True이면 클라우드로 재추출"""
        # 텍스트가 너무 길면 분할 처리
        if len(text) > max_chars:
            return self._extract_chunked(text, max_chars)

        prompt = SOP_EXTRACTION_PROMPT.format(text=text[:max_chars])

        # 1차: 로컬 LLM 시도
        response = self.llm.invoke([HumanMessage(content=prompt)])
        try:
            result = json.loads(response.content)
        except json.JSONDecodeError:
            result = self._retry_extraction(text)

        # 신뢰도 낮으면 review_required 강제 설정
        confidence = result.get("extraction_confidence", 1.0)
        if confidence < self._router.threshold:
            result["review_required"] = True

        # SOP-F15: review_required 항목은 클라우드 LLM으로 재추출
        if result.get("review_required") and self.fallback_llm is not None:
            cloud_response = self.fallback_llm.invoke([HumanMessage(content=prompt)])
            try:
                result = json.loads(cloud_response.content)
                result["_source"] = "cloud_fallback"
            except json.JSONDecodeError:
                pass  # 클라우드도 실패하면 로컬 결과 유지
        else:
            result["_source"] = "local"

        return result

    def _extract_chunked(self, text: str, max_chars: int) -> dict:
        """긴 문서를 섹션별로 분할하여 추출 후 병합"""
        chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars - 500)]
        all_steps = []
        all_checklist = []
        all_cautions = []
        step_offset = 0

        for chunk in chunks:
            result = self.extract(chunk, max_chars)
            for step in result.get("steps", []):
                step["step_no"] += step_offset
                all_steps.append(step)
            step_offset = len(all_steps)
            all_checklist.extend(result.get("checklist_items", []))
            all_cautions.extend(result.get("cautions", []))

        return {
            "steps": all_steps,
            "checklist_items": all_checklist,
            "cautions": all_cautions,
            "review_required": True,  # 분할 추출 시 항상 검토 필요
            "extraction_confidence": 0.65
        }
```

---

### Phase 2 — SOP 관리 API

#### 2-1. 엔드포인트 목록

```
# SOP 업로드 및 추출 실행
POST /api/v1/sops/extract
  Content-Type: multipart/form-data
  Body: file, department_id, ocr_engine (optional: "tesseract"|"google")
  Response: { sop_id, extraction_result, review_required, confidence }

# SOP 목록 조회
GET /api/v1/sops
  Query: department?, status (draft|active|archived)?, tags?

# SOP 단건 조회
GET /api/v1/sops/{sop_id}

# SOP 수동 수정 (검토 단계)
PUT /api/v1/sops/{sop_id}
  Body: { title, steps, checklist_items, cautions, tags }

# SOP 확정 (draft → active)
POST /api/v1/sops/{sop_id}/publish
  → review_required=false로 변경
  → RAG 인덱싱 트리거
  → 부서 직원 알림 발송

# SOP 신규 버전 생성 (기존 버전 유지)
POST /api/v1/sops/{sop_id}/versions
  Body: 파일 또는 직접 편집 내용

# SOP 아카이브
DELETE /api/v1/sops/{sop_id}

# SOP PDF 출력
GET /api/v1/sops/{sop_id}/export?format=pdf|checklist

# SOP Acknowledge
POST /api/v1/sops/{sop_id}/acknowledge
GET /api/v1/sops/{sop_id}/acknowledge-stats (Manager+)
```

#### 2-2. SOP 처리 통합 서비스

```python
# app/sop/service.py

import uuid
import time
from app.sop.ocr import OCRProcessor
from app.sop.extractor import SOPExtractor
from app.database.crud import create_sop, update_sop
from app.rag.ingest import ingest_sop_to_vector_store
from app.notifications.service import notify_department

class SOPService:
    def __init__(self):
        self.ocr = OCRProcessor()
        self.extractor = SOPExtractor()

    def process_upload(
        self,
        file_path: str,
        file_type: str,
        department_id: str,
        uploaded_by: int,
        ocr_engine: str = "tesseract"
    ) -> dict:
        start = time.perf_counter()

        # Step 1: 텍스트 추출
        if file_type == "pdf":
            if self._is_scanned_pdf(file_path):
                pages = self.ocr.extract_text_from_scanned_pdf(file_path)
                full_text = "\n\n".join(p["text"] for p in pages)
                avg_confidence = sum(p["confidence"] for p in pages) / len(pages)
            else:
                full_text = self._extract_text_pdf(file_path)
                avg_confidence = 1.0
        elif file_type == "docx":
            full_text = self._extract_text_docx(file_path)
            avg_confidence = 1.0
        else:
            full_text = open(file_path, encoding="utf-8").read()
            avg_confidence = 1.0

        # Step 2: AI 구조 추출
        extraction = self.extractor.extract(full_text)

        # Step 3: DB 저장 (draft 상태)
        sop_id = str(uuid.uuid4())
        sop_data = {
            "id": sop_id,
            "title": extraction.get("title", "제목 미추출"),
            "department_id": department_id,
            "steps": extraction.get("steps", []),
            "checklist_items": extraction.get("checklist_items", []),
            "cautions": extraction.get("cautions", []),
            "review_required": extraction.get("review_required", True),
            "extraction_confidence": extraction.get("extraction_confidence", 0.0),
            "ocr_confidence": avg_confidence,
            "source_file": file_path,
            "status": "draft",
            "version": "1.0",
            "created_by": uploaded_by,
        }
        create_sop(sop_data)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {**sop_data, "processing_time_ms": elapsed_ms}

    def publish(self, sop_id: str, publisher_id: int):
        """SOP 확정: draft → active, RAG 인덱싱, 알림 발송"""
        sop = get_sop(sop_id)
        update_sop(sop_id, {"status": "active", "review_required": False})

        # RAG 인덱싱 (SOP 내용을 벡터 DB에 추가)
        ingest_sop_to_vector_store(sop)

        # 부서 직원 알림 발송
        notify_department(
            department_id=sop["department_id"],
            title=f"[SOP 업데이트] {sop['title']}",
            message=f"새 버전의 SOP가 등록되었습니다. 확인 후 Acknowledge 처리해 주세요.",
            link=f"/sops/{sop_id}"
        )

    def _is_scanned_pdf(self, file_path: str) -> bool:
        """PDF 내 텍스트 레이어 유무 확인"""
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        text = "".join(page.get_text() for page in doc)
        return len(text.strip()) < 100  # 텍스트 없으면 스캔 PDF로 판단
```

---

### Phase 3 — SOP 에디터 (웹 인터페이스, SOP-F20~22)

#### 3-1. SOP 에디터 컴포넌트 구조

```
/sops/[sop_id]/edit 페이지

┌─────────────────────────────────────────────────────┐
│  SOP 에디터                              [저장] [확정]│
├──────────────────────────┬──────────────────────────┤
│  📋 기본 정보             │  👁 미리보기              │
│  제목: [          ]      │                           │
│  부서: [프런트   ▼]      │  # 체크인 표준 절차       │
│  태그: [체크인 ×] [+]    │                           │
├──────────────────────────┤  Step 1: 고객 도착 시 인사 │
│  📝 절차 단계             │  Step 2: 예약 확인        │
│  ┌─────────────────────┐ │  ...                      │
│  │ Step 1 [↑↓] [×]    │ │                           │
│  │ 액션: [        ]    │ │  □ 신분증 확인            │
│  │ 담당: [        ]    │ │  □ 결제 수단 등록         │
│  │ 시간: [  ]분        │ │                           │
│  │ 메모: [        ]    │ │  ⚠️ 주의사항              │
│  └─────────────────────┘ │  - 오버부킹 시 → 매니저 호출│
│  [+ 단계 추가]            │                           │
├──────────────────────────┤                           │
│  ✅ 체크리스트 항목        │                           │
│  □ [신분증 확인 완료  ] ×│                           │
│  □ [결제 등록 완료    ] ×│                           │
│  [+ 항목 추가]            │                           │
├──────────────────────────┤                           │
│  ⚠️ 주의사항              │                           │
│  [텍스트에리어          ]│                           │
└──────────────────────────┴───────────────────────────┘
```

#### 3-2. PDF Export (SOP-F22)

```python
# app/sop/export.py

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.units import cm
from io import BytesIO

def export_sop_to_pdf(sop: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2.5*cm, rightMargin=2.5*cm)
    styles = getSampleStyleSheet()
    story = []

    # 제목
    story.append(Paragraph(sop["title"], styles["Title"]))
    story.append(Paragraph(f"부서: {sop['department_id']} | 버전: {sop['version']} | 최종 수정: {sop['updated_at']}", styles["Normal"]))
    story.append(Spacer(1, 0.5*cm))

    # 절차 단계
    story.append(Paragraph("표준 절차", styles["Heading2"]))
    for step in sop["steps"]:
        text = f"Step {step['step_no']}. {step['action']}"
        if step.get("responsible"):
            text += f" <i>(담당: {step['responsible']})</i>"
        story.append(Paragraph(text, styles["Normal"]))
        if step.get("notes"):
            story.append(Paragraph(f"  → {step['notes']}", styles["Italic"]))

    # 체크리스트
    if sop.get("checklist_items"):
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("점검 체크리스트", styles["Heading2"]))
        for item in sop["checklist_items"]:
            required_mark = " ★" if item.get("required") else ""
            story.append(Paragraph(f"□ {item['text']}{required_mark}", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
```

---

### Phase 4 — RAG 인덱싱 연동 (SOP-F13 + RAG-F01 연계)

확정된 SOP는 RAG 벡터 DB에도 인덱싱되어 직원이 자연어로 검색 가능.

```python
# app/rag/ingest.py 에 추가

def ingest_sop_to_vector_store(sop: dict, collection_name: str = "hotel_docs"):
    """확정된 SOP를 구조화된 텍스트로 변환 후 벡터 DB 추가"""
    # 구조화된 SOP를 자연어 텍스트로 직렬화
    text_parts = [f"# {sop['title']}\n"]

    for step in sop.get("steps", []):
        text_parts.append(
            f"Step {step['step_no']}: {step['action']}"
            + (f" (담당: {step['responsible']})" if step.get("responsible") else "")
            + (f" - {step['notes']}" if step.get("notes") else "")
        )

    for item in sop.get("checklist_items", []):
        text_parts.append(f"체크: {item['text']}")

    for caution in sop.get("cautions", []):
        text_parts.append(f"주의: {caution}")

    full_text = "\n".join(text_parts)

    # 문서 객체 생성
    from langchain_core.documents import Document
    doc = Document(
        page_content=full_text,
        metadata={
            "source": f"sop/{sop['id']}",
            "source_id": sop["id"],
            "title": sop["title"],
            "department": sop["department_id"],
            "version": sop["version"],
            "doc_type": "sop",
        }
    )

    vector_store = get_vector_store(collection_name)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap
    )
    chunks = splitter.split_documents([doc])
    vector_store.add_documents(chunks)
```

---

## 4. 파일 구조 변경 계획

```
app/
├── sop/                         # 신규 모듈
│   ├── __init__.py
│   ├── ocr.py                   # OCR 처리 (Tesseract/Google Vision)
│   ├── extractor.py             # AI 구조 추출 (GPT-4o-mini)
│   ├── service.py               # 비즈니스 로직 통합
│   └── export.py                # PDF/체크리스트 Export
│
├── api/
│   └── routes/
│       └── sops.py              # SOP CRUD API
│
└── database/
    └── models.py                # SOP, SOPVersion, SOPAcknowledgement 테이블 추가
```

---

## 5. DB 스키마 (SOP 관련)

```sql
CREATE TABLE sops (
    id                   VARCHAR(36)  PRIMARY KEY,
    title                VARCHAR(255) NOT NULL,
    department_id        VARCHAR(50)  REFERENCES departments(id),
    version              VARCHAR(20)  NOT NULL DEFAULT '1.0',
    status               ENUM('draft','active','archived') NOT NULL DEFAULT 'draft',
    steps                JSON,            -- 절차 단계 배열
    checklist_items      JSON,            -- 체크리스트 항목 배열
    cautions             JSON,            -- 주의사항 배열
    tags                 JSON,
    source_file          VARCHAR(500),    -- 원본 파일 경로
    review_required      BOOLEAN DEFAULT TRUE,
    extraction_confidence DECIMAL(4,3),   -- AI 추출 신뢰도
    ocr_confidence       DECIMAL(4,3),    -- OCR 신뢰도
    chroma_chunk_ids     JSON,            -- RAG 인덱싱된 청크 ID
    created_by           INT REFERENCES users(id),
    updated_by           INT REFERENCES users(id),
    published_by         INT REFERENCES users(id),
    published_at         DATETIME,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_department (department_id),
    INDEX idx_status (status)
);

CREATE TABLE sop_version_history (
    id           INT PRIMARY KEY AUTO_INCREMENT,
    sop_id       VARCHAR(36) NOT NULL REFERENCES sops(id),
    version      VARCHAR(20) NOT NULL,
    snapshot     JSON NOT NULL,       -- 해당 버전의 SOP 전체 스냅샷
    changed_by   INT REFERENCES users(id),
    changed_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    change_summary TEXT,
    INDEX idx_sop_id (sop_id)
);

CREATE TABLE sop_acknowledgements (
    id       INT PRIMARY KEY AUTO_INCREMENT,
    sop_id   VARCHAR(36) NOT NULL REFERENCES sops(id),
    version  VARCHAR(20) NOT NULL,
    user_id  INT NOT NULL REFERENCES users(id),
    acked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ack (sop_id, version, user_id)
);
```

---

## 6. 의존성 추가

```
# requirements.txt 추가
pytesseract>=0.3.10      # OCR (Tesseract 엔진 별도 설치 필요)
pdf2image>=1.17.0        # PDF → 이미지 변환
Pillow>=10.0.0           # 이미지 처리
PyMuPDF>=1.23.0          # PDF 텍스트 레이어 감지 (fitz)
reportlab>=4.0.0         # PDF 출력 생성
python-docx>=1.1.0       # DOCX 텍스트 추출

# 시스템 의존성 (Dockerfile에 추가)
# tesseract-ocr, tesseract-ocr-kor, poppler-utils
```

---

## 7. Dockerfile 수정

```dockerfile
FROM python:3.11-slim

# 시스템 패키지
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-kor \
    tesseract-ocr-eng \
    poppler-utils \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 8. 테스트 전략

| 테스트 | 방법 | 목표 |
|--------|------|------|
| OCR 정확도 | 한국어 샘플 인쇄 문서 10종 테스트 | 95% 이상 |
| AI 추출 정확도 | SOP 샘플 10종 golden set 비교 | 85% 이상 |
| 검토 플래그 | 낮은 신뢰도 문서에 review_required=true 확인 | 100% |
| PDF Export | 생성된 PDF 페이지/내용 일치 확인 | 정상 생성 |
| RAG 연동 | 확정 SOP 내용이 채팅 검색에서 반환되는지 확인 | 정상 반환 |

---

## 9. 구현 체크리스트

### Phase 1 (OCR + 추출)
- [ ] `pytesseract`, `pdf2image`, `PyMuPDF` 의존성 추가
- [ ] `app/sop/ocr.py` OCRProcessor 구현
- [ ] `app/sop/extractor.py` SOPExtractor 구현
- [ ] 스캔 PDF 판별 로직 (`_is_scanned_pdf`) 구현
- [ ] Dockerfile에 tesseract 시스템 패키지 추가

### Phase 2 (API)
- [ ] `sops` DB 테이블 생성 마이그레이션
- [ ] `app/sop/service.py` SOPService 구현
- [ ] `app/api/routes/sops.py` 엔드포인트 구현
- [ ] `/sops/extract`, `/sops/{id}/publish` 핵심 엔드포인트 우선 구현

### Phase 3 (에디터 + Export)
- [ ] Next.js SOP 에디터 페이지 구현
- [ ] `reportlab` PDF export 구현
- [ ] Acknowledge 기능 구현

### Phase 4 (RAG 연동)
- [ ] `ingest_sop_to_vector_store()` 구현
- [ ] SOP 버전 교체 시 기존 청크 삭제 처리
