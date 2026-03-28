# Plan: SOP 디지털화 — OCR 파이프라인 / AI 추출 상세 설계

> **상위 문서**: [plan-sop-digitalization.md](./plan-sop-digitalization.md)
> **내용**: OCR 품질 보정, AI 추출 프롬프트 전략, 검토 워크플로 상세

---

## 1. OCR 파이프라인 상세

### 1-1. PDF 유형 판별 흐름

```
PDF 업로드
    │
    ▼
PyMuPDF로 텍스트 레이어 확인
    │
    ├─ 텍스트 500자 이상 → 텍스트 PDF
    │      → pdfplumber로 직접 추출
    │      → 페이지별 구조(테이블, 목록) 보존
    │
    └─ 텍스트 500자 미만 → 스캔 PDF
           → pdf2image로 이미지 변환 (300 DPI)
           → 페이지별 전처리 (이진화, 노이즈 제거)
           → Tesseract OCR (kor+eng)
           → 신뢰도 점수 기록
```

### 1-2. 이미지 전처리 (OCR 정확도 향상)

```python
# app/sop/ocr.py

import cv2
import numpy as np
from PIL import Image

def preprocess_image(pil_image: Image.Image) -> Image.Image:
    """OCR 정확도를 높이기 위한 이미지 전처리"""
    # PIL → OpenCV 변환
    img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    # 1. 그레이스케일 변환
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. 노이즈 제거 (가우시안 블러)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)

    # 3. 이진화 (Otsu's thresholding) - 배경/텍스트 분리
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 4. 기울기 보정 (Deskew)
    coords = np.column_stack(np.where(binary < 128))
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) > 0.5:  # 0.5도 이상 기울어진 경우만 보정
            (h, w) = binary.shape
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            binary = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # 5. 해상도 업스케일 (작은 폰트 대응)
    scale_factor = 1.5
    h, w = binary.shape
    binary = cv2.resize(binary, (int(w * scale_factor), int(h * scale_factor)), interpolation=cv2.INTER_CUBIC)

    return Image.fromarray(binary)
```

### 1-3. 테이블 구조 보존 (pdfplumber 활용)

```python
# app/sop/ocr.py

import pdfplumber

def extract_structured_text(file_path: str) -> list[dict]:
    """텍스트 PDF에서 테이블 포함 구조적 텍스트 추출"""
    results = []

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            page_data = {"page": page_num, "text_blocks": [], "tables": []}

            # 일반 텍스트 블록 (좌표 포함)
            words = page.extract_words()
            text = page.extract_text() or ""
            page_data["text"] = text

            # 테이블 추출
            tables = page.extract_tables()
            for table in tables:
                # None 셀 처리
                cleaned_table = [
                    [cell if cell else "" for cell in row]
                    for row in table if table
                ]
                page_data["tables"].append(cleaned_table)

            results.append(page_data)

    return results

def format_table_as_text(table: list[list[str]]) -> str:
    """테이블을 텍스트로 직렬화 (체크리스트 인식을 위해)"""
    if not table:
        return ""
    lines = []
    for row in table:
        lines.append(" | ".join(str(cell) for cell in row))
    return "\n".join(lines)
```

---

## 2. AI 추출 프롬프트 전략

### 2-1. 문서 유형별 특화 프롬프트

```python
# app/sop/extractor.py

PROMPT_BY_TYPE = {
    "procedure": """
다음은 호텔 운영 표준 절차(SOP) 문서입니다.
아래 항목을 정확히 추출하세요:

[추출 대상]
- steps: "1.", "①", "Step 1" 등으로 시작하는 순서형 절차 단계
  각 단계에서 다음을 추출:
  * action: 수행할 행동 (동사로 시작하는 명확한 문장)
  * responsible: 담당자/역할 (없으면 null)
  * duration_min: 소요 시간(분 단위 숫자, 없으면 null)
  * notes: 주의사항이나 부가 설명 (없으면 null)

- checklist_items: "□", "○", "체크", "확인" 등으로 표시된 항목
  * text: 체크해야 할 내용
  * required: 필수 여부 (★, 필수, required 표시 시 true, 기본 true)

- cautions: "주의", "경고", "NOTE", "※" 등으로 시작하는 내용

[반환 형식 - 반드시 JSON만 반환]
{
  "title": "문서 제목",
  "steps": [...],
  "checklist_items": [...],
  "cautions": [...],
  "review_required": false,
  "extraction_confidence": 0.90
}
""",

    "checklist": """
다음은 점검 체크리스트 문서입니다.
"□", "○", "[ ]" 등으로 시작하는 모든 항목을 체크리스트로 추출하세요.

[반환 형식]
{
  "title": "체크리스트 제목",
  "steps": [],
  "checklist_items": [
    {"text": "항목 내용", "required": true, "category": "카테고리(있으면)"}
  ],
  "cautions": [],
  "review_required": false,
  "extraction_confidence": 0.90
}
""",

    "manual": """
다음은 업무 매뉴얼/가이드 문서입니다.
섹션/챕터 구조를 기준으로 핵심 절차를 추출하세요.
(엄밀한 단계 순서보다 섹션별 요점 정리에 집중)
...
"""
}

class SOPExtractor:
    def detect_document_type(self, text: str) -> str:
        """문서 텍스트로 유형 자동 판별"""
        procedure_keywords = ["step", "절차", "단계", "①", "②", "1.", "2."]
        checklist_keywords = ["□", "○", "[ ]", "체크리스트", "점검표"]

        proc_count = sum(text.count(k) for k in procedure_keywords)
        check_count = sum(text.count(k) for k in checklist_keywords)

        if check_count > 5 and check_count > proc_count:
            return "checklist"
        elif proc_count > 3:
            return "procedure"
        else:
            return "manual"
```

### 2-2. 신뢰도 점수 산정 및 클라우드 라우팅 로직 (SOP-F15)

```python
from app.core.config import settings

def calculate_extraction_confidence(result: dict, original_text: str) -> float:
    """
    신뢰도 산정 기준:
    - steps가 1개 이상 추출됨: +0.3
    - 각 step의 action이 10자 이상: +0.2
    - checklist_items가 추출됨: +0.2
    - title이 원문에 존재하는 문자열임: +0.2
    - 원문 길이 대비 추출 커버리지: +0.1
    """
    score = 0.0

    steps = result.get("steps", [])
    if len(steps) >= 1:
        score += 0.3
    if steps and all(len(s.get("action", "")) >= 10 for s in steps):
        score += 0.2

    if result.get("checklist_items"):
        score += 0.2

    title = result.get("title", "")
    if title and title in original_text:
        score += 0.2

    # 추출 내용이 원문의 30% 이상 커버하면 추가 점수
    extracted_text = " ".join(
        s.get("action", "") + " " + s.get("notes", "")
        for s in steps
    )
    coverage = len(extracted_text) / max(len(original_text), 1)
    if coverage > 0.3:
        score += 0.1

    return min(round(score, 2), 1.0)


def should_route_to_cloud(result: dict, original_text: str) -> bool:
    """
    SOP-F15: 로컬 추출 결과를 클라우드 LLM으로 재처리해야 하는지 판단.
    - 신뢰도 < LOCAL_LLM_CONFIDENCE_THRESHOLD 이면 클라우드 필요
    - review_required=True 이면 클라우드 필요
    """
    threshold = settings.local_llm_confidence_threshold  # default 0.70
    confidence = calculate_extraction_confidence(result, original_text)
    return confidence < threshold or result.get("review_required", False)
```

---

## 3. 검토 워크플로 상세

### 3-1. 상태 머신

```
[업로드]
    │
    ▼
[draft] ─────────────── AI 추출 완료, review_required 판단
    │
    ├─ review_required=false (신뢰도 ≥ 0.85)
    │   → 자동으로 검토 권장 안내 + 바로 게시 가능
    │
    └─ review_required=true (신뢰도 < 0.85)
        → 담당자에게 검토 필요 알림
        → 에디터에서 수동 수정 가능
        │
        ▼
   [under_review]  (담당자가 에디터 열면 자동 전환)
        │
        ├─ 수정 후 [publish] 클릭
        │       ↓
        │  [active] → RAG 인덱싱 + 부서 알림
        │
        └─ 취소 시 [draft] 복귀
```

### 3-2. 검토 UI 에디터 동작

- 추출된 각 step/checklist 항목 옆에 AI 추출 결과임을 시각적으로 표시 (파란색 배지)
- 신뢰도 낮은 항목은 노란색 배경 + "검토 필요" 뱃지
- 담당자가 내용 수정 시 해당 항목은 "수동 확인됨"으로 표시 변경
- 모든 항목이 수동 확인되거나 신뢰도 ≥ 0.85이면 "확정" 버튼 활성화

```typescript
// components/sop/SOPEditor.tsx

interface SOPStep {
  step_no: number
  action: string
  responsible: string | null
  duration_min: number | null
  notes: string | null
  ai_extracted: boolean   // AI가 추출한 항목 여부
  manually_verified: boolean  // 담당자가 확인한 항목 여부
  confidence?: number     // 이 항목의 추출 신뢰도
}

function StepEditor({ step, onChange }: { step: SOPStep; onChange: (s: SOPStep) => void }) {
  const needsReview = step.ai_extracted && !step.manually_verified && (step.confidence ?? 1) < 0.7

  return (
    <div className={`border rounded-lg p-3 ${needsReview ? 'border-yellow-400 bg-yellow-50' : 'border-gray-200'}`}>
      {needsReview && (
        <div className="text-yellow-700 text-xs mb-2 flex items-center gap-1">
          ⚠️ 검토 필요 (AI 추출 신뢰도: {((step.confidence ?? 0) * 100).toFixed(0)}%)
        </div>
      )}
      {step.ai_extracted && !step.manually_verified && (
        <span className="text-blue-600 text-xs bg-blue-50 px-1 rounded">AI 추출</span>
      )}
      <input
        value={step.action}
        onChange={(e) => onChange({ ...step, action: e.target.value, manually_verified: true })}
        className="w-full border-b focus:outline-none py-1"
        placeholder="절차 내용"
      />
      {/* 담당자, 시간, 메모 필드 */}
    </div>
  )
}
```

---

## 4. 알림 시스템 연동

### SOP 관련 알림 트리거

| 트리거 | 수신 대상 | 내용 |
|--------|---------|------|
| 추출 완료 (review_required=true) | 업로드한 담당자 | "검토가 필요합니다. 에디터에서 확인해 주세요." |
| 추출 완료 (review_required=false) | 업로드한 담당자 | "추출이 완료되었습니다. 확인 후 게시해 주세요." |
| SOP 확정(publish) | 해당 부서 전 직원 | "새 SOP가 등록되었습니다. 확인 후 Acknowledge 해주세요." |
| Acknowledge 마감 D-2 미완료 | 미완료 직원 | "SOP 확인 요청이 있습니다. 마감 전 완료해 주세요." |

### 알림 서비스 구조

```python
# app/notifications/service.py

from enum import Enum
from dataclasses import dataclass

class NotificationChannel(Enum):
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"

@dataclass
class Notification:
    user_ids: list[int]
    title: str
    message: str
    link: str
    channels: list[NotificationChannel]

class NotificationService:
    def send(self, notification: Notification):
        for channel in notification.channels:
            if channel == NotificationChannel.EMAIL:
                self._send_email(notification)
            elif channel == NotificationChannel.PUSH:
                self._send_push(notification)

    def notify_department(
        self,
        department_id: str,
        title: str,
        message: str,
        link: str,
        channels: list[NotificationChannel] = None
    ):
        if channels is None:
            channels = [NotificationChannel.EMAIL, NotificationChannel.PUSH]

        # 부서 소속 활성 사용자 조회
        users = get_users_by_department(department_id)
        user_ids = [u.id for u in users if u.is_active]

        self.send(Notification(
            user_ids=user_ids,
            title=title,
            message=message,
            link=link,
            channels=channels
        ))

    def _send_email(self, notification: Notification):
        """SMTP를 통한 이메일 발송 (실패 시 3회 재시도)"""
        import smtplib
        from email.mime.text import MIMEText
        from tenacity import retry, stop_after_attempt, wait_exponential

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
        def _send():
            # smtplib 구현...
            pass

        _send()
```

---

## 5. 성능 최적화 고려사항

| 항목 | 문제 | 해결 방안 |
|------|------|---------|
| OCR 처리 시간 | A4 10페이지 기준 50초+ | Celery 비동기 작업큐로 처리, 진행 상태 폴링 |
| AI 추출 API 비용 | 페이지당 GPT 호출 | 페이지 배치 처리, 캐싱 |
| 대용량 PDF | 100페이지 이상 처리 | 섹션별 분할 처리 + 병렬 OCR |
| 이미지 전처리 메모리 | 고해상도 이미지 | 스트리밍 처리, 처리 후 즉시 해제 |

### Celery 비동기 처리 구조

```python
# app/tasks/sop_tasks.py

from celery import Celery

celery = Celery("hotel_rag", broker="redis://localhost:6379/0")

@celery.task(bind=True, max_retries=3)
def process_sop_upload_task(self, file_path: str, metadata: dict):
    """비동기 SOP 처리 태스크"""
    try:
        service = SOPService()
        result = service.process_upload(
            file_path=file_path,
            file_type=metadata["file_type"],
            department_id=metadata["department_id"],
            uploaded_by=metadata["uploaded_by"]
        )
        # 완료 알림
        notify_user(metadata["uploaded_by"], "SOP 처리 완료", result["sop_id"])
        return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)

# API 엔드포인트에서 호출
@router.post("/sops/extract")
async def extract_sop(file: UploadFile, ...):
    # 파일 저장
    file_path = save_upload(file)

    # 비동기 작업 시작
    task = process_sop_upload_task.delay(file_path, metadata)

    return {"task_id": task.id, "status": "processing"}

# 진행 상태 폴링
@router.get("/sops/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = AsyncResult(task_id)
    return {"status": task.status, "result": task.result if task.ready() else None}
```
