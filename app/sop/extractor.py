"""SOP AI 구조 추출 — 로컬 LLM 우선, review_required 시 클라우드 폴백 (SOP-F10~15)"""

import json
import logging

from langchain_core.messages import HumanMessage

from app.core.llm_router import TaskTier, llm_router

logger = logging.getLogger(__name__)

# ── 문서 유형별 프롬프트 ─────────────────────────────────────

_PROMPT_PROCEDURE = """\
당신은 호텔 운영 문서 분석 전문가입니다.
다음 표준 절차(SOP) 문서에서 구성 요소를 정확히 추출하세요.

[추출 규칙]
- steps: "1.", "①", "Step 1" 등으로 시작하는 순서형 절차 단계
  * action: 수행 행동 (동사 시작 명확한 문장)
  * responsible: 담당자/역할 (없으면 null)
  * duration_min: 소요 시간(분, 없으면 null)
  * notes: 주의사항/부가설명 (없으면 null)
- checklist_items: "□", "○", "[ ]", "체크", "확인" 항목
  * text: 체크 내용
  * required: 필수 여부 (★/필수 표시 시 true, 기본 true)
- cautions: "주의", "경고", "NOTE", "※" 로 시작하는 내용
- review_required: 추출 확신도 70% 미만 항목 존재 시 true
- extraction_confidence: 0.0~1.0 추출 전체 신뢰도

반드시 JSON만 반환:
{{
  "title": "문서 제목",
  "steps": [{{"step_no": 1, "action": "...", "responsible": null, "duration_min": null, "notes": null}}],
  "checklist_items": [{{"text": "...", "required": true}}],
  "cautions": [],
  "review_required": false,
  "extraction_confidence": 0.90
}}

[문서 텍스트]
{text}
"""

_PROMPT_CHECKLIST = """\
다음은 점검 체크리스트 문서입니다.
"□", "○", "[ ]" 등으로 시작하는 모든 항목을 체크리스트로 추출하세요.

반드시 JSON만 반환:
{{
  "title": "체크리스트 제목",
  "steps": [],
  "checklist_items": [{{"text": "항목 내용", "required": true}}],
  "cautions": [],
  "review_required": false,
  "extraction_confidence": 0.90
}}

[문서 텍스트]
{text}
"""

_PROMPT_MANUAL = """\
다음은 호텔 업무 매뉴얼/가이드 문서입니다.
섹션 구조를 기준으로 핵심 절차와 지침을 추출하세요.

반드시 JSON만 반환:
{{
  "title": "매뉴얼 제목",
  "steps": [{{"step_no": 1, "action": "...", "responsible": null, "duration_min": null, "notes": null}}],
  "checklist_items": [],
  "cautions": [],
  "review_required": false,
  "extraction_confidence": 0.75
}}

[문서 텍스트]
{text}
"""

_PROMPTS = {
    "procedure": _PROMPT_PROCEDURE,
    "checklist": _PROMPT_CHECKLIST,
    "manual": _PROMPT_MANUAL,
}

_FALLBACK_RESULT: dict = {
    "title": "추출 실패",
    "steps": [],
    "checklist_items": [],
    "cautions": [],
    "review_required": True,
    "extraction_confidence": 0.0,
}


# ── 신뢰도 산정 ───────────────────────────────────────────────


def calculate_extraction_confidence(result: dict, original_text: str) -> float:
    """추출 결과 품질 기반 신뢰도 점수 계산 (0.0 ~ 1.0)"""
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

    extracted = " ".join(
        (s.get("action") or "") + " " + (s.get("notes") or "")
        for s in steps
    )
    coverage = len(extracted) / max(len(original_text), 1)
    if coverage > 0.3:
        score += 0.1

    return min(round(score, 2), 1.0)


# ── SOPExtractor ─────────────────────────────────────────────


class SOPExtractor:
    """SOP-F10~15: 로컬 LLM 우선 구조 추출, review_required=True 시 클라우드 재추출"""

    MAX_CHARS = 6000
    CHUNK_OVERLAP = 500

    def __init__(self) -> None:
        self._tier = TaskTier.LOCAL_FIRST
        self.llm = llm_router.get_llm(self._tier)
        self.fallback_llm = llm_router.get_fallback(self._tier)

    def detect_document_type(self, text: str) -> str:
        """텍스트 패턴으로 문서 유형 자동 판별"""
        procedure_kw = ["step", "절차", "단계", "①", "②", "1.", "2.", "3."]
        checklist_kw = ["□", "○", "[ ]", "체크리스트", "점검표", "checklist"]

        proc_count = sum(text.lower().count(k.lower()) for k in procedure_kw)
        check_count = sum(text.count(k) for k in checklist_kw)

        if check_count > 5 and check_count > proc_count:
            return "checklist"
        if proc_count >= 3:
            return "procedure"
        return "manual"

    def extract(self, text: str) -> dict:
        """SOP-F15: 로컬 LLM 1차 추출 → 신뢰도 미달 시 클라우드 재추출"""
        if len(text) > self.MAX_CHARS:
            return self._extract_chunked(text)

        doc_type = self.detect_document_type(text)
        prompt = _PROMPTS[doc_type].format(text=text[: self.MAX_CHARS])

        # 1차: 로컬 LLM
        result = self._invoke(self.llm, prompt)
        result.setdefault("_source", "local")

        # 신뢰도 재계산
        calc_conf = calculate_extraction_confidence(result, text)
        if calc_conf < llm_router.threshold:
            result["review_required"] = True
            result["extraction_confidence"] = calc_conf

        # 클라우드 폴백 (review_required=True 이면 재추출)
        if result.get("review_required") and self.fallback_llm is not None:
            logger.info("SOP 추출 신뢰도 낮음(%.2f) → 클라우드 재추출", calc_conf)
            cloud_result = self._invoke(self.fallback_llm, prompt)
            if cloud_result.get("extraction_confidence", 0) > result.get("extraction_confidence", 0):
                cloud_result["_source"] = "cloud_fallback"
                return cloud_result

        return result

    def _invoke(self, llm, prompt: str) -> dict:
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            # JSON 블록 파싱 (```json ... ``` 형태 대응)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("LLM 응답 파싱 실패: %s", exc)
            return dict(_FALLBACK_RESULT)

    def _extract_chunked(self, text: str) -> dict:
        """긴 문서를 청크별 추출 후 병합 (항상 review_required=True)"""
        chunks = [
            text[i: i + self.MAX_CHARS]
            for i in range(0, len(text), self.MAX_CHARS - self.CHUNK_OVERLAP)
        ]
        all_steps: list = []
        all_checklist: list = []
        all_cautions: list = []

        for chunk in chunks:
            r = self.extract(chunk)
            for step in r.get("steps", []):
                step["step_no"] = len(all_steps) + 1
                all_steps.append(step)
            all_checklist.extend(r.get("checklist_items", []))
            all_cautions.extend(r.get("cautions", []))

        return {
            "title": "분할 추출 문서",
            "steps": all_steps,
            "checklist_items": all_checklist,
            "cautions": list(dict.fromkeys(all_cautions)),  # 중복 제거
            "review_required": True,
            "extraction_confidence": 0.65,
            "_source": "chunked",
        }
