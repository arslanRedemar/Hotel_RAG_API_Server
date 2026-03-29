"""Work Order AI 분류 엔진 — 규칙 우선, 신뢰도 미달 시 LLM 폴백 (WO-F10, F11, F14)"""

import json
import logging
import re
from dataclasses import dataclass

from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"전기", "에어컨", "배관", "가구", "청결", "기타"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}

# ── 규칙 기반 분류 사전 ───────────────────────────────────────

_CATEGORY_RULES: list[tuple[list[str], str]] = [
    (["전기", "전구", "누전", "전선", "콘센트", "조명", "스위치", "형광등", "불꽃", "감전"], "전기"),
    (["에어컨", "냉방", "난방", "온도", "히터", "보일러", "환풍기", "공기", "환기"], "에어컨"),
    (["배관", "변기", "수도", "배수", "누수", "물", "파이프", "하수", "세면대", "샤워"], "배관"),
    (["가구", "침대", "소파", "책상", "의자", "서랍", "문", "잠금", "창문", "흔들"], "가구"),
    (["청결", "더럽", "냄새", "곰팡이", "먼지", "얼룩", "오염", "쓰레기", "청소"], "청결"),
]

_CRITICAL_KEYWORDS = [
    "누전", "불꽃", "감전", "화재", "가스", "가스 누출", "폭발", "비상구",
    "물이 없", "물 없음", "투숙 불가", "물이 전혀", "수도 없음",
    "히터 고장", "히터가 완전", "히터 작동 안", "보일러 고장", "매우 추운",
]
_HIGH_KEYWORDS = ["vip", "당일", "재판매", "오늘 체크인", "오늘 입실"]
_LOW_KEYWORDS = ["빈 객실", "미입실", "예방 점검", "예방정비", "빈방", "공실"]


@dataclass
class ClassificationResult:
    category: str
    severity: str
    confidence: float
    reasoning: str = ""


class WorkOrderClassifier:
    """WO-F14: 규칙 기반 우선, 신뢰도 미달 시 OpenAI 폴백"""

    confidence_threshold: float = 0.8

    def classify(self, description: str) -> ClassificationResult:
        """공개 진입점 — 규칙 → LLM 폴백"""
        result = self.classify_with_rules(description)
        if result.confidence < self.confidence_threshold:
            logger.info("분류 신뢰도 낮음(%.2f) → LLM 폴백", result.confidence)
            try:
                result = self._classify_with_llm(description)
            except Exception as exc:
                logger.warning("LLM 분류 실패, 규칙 결과 사용: %s", exc)
        return result

    def classify_with_rules(self, description: str) -> ClassificationResult:
        """규칙 기반 분류 (WO-F10, F11)"""
        text = description.lower()
        category = self._detect_category(text)
        severity = self._detect_severity(text)
        confidence = self._calc_confidence(text, category)
        return ClassificationResult(
            category=category,
            severity=severity,
            confidence=confidence,
            reasoning="규칙 기반 분류",
        )

    def _detect_category(self, text: str) -> str:
        for keywords, cat in _CATEGORY_RULES:
            if any(kw in text for kw in keywords):
                return cat
        return "기타"

    def _detect_severity(self, text: str) -> str:
        if any(kw in text for kw in _CRITICAL_KEYWORDS):
            return "critical"
        # 복합 조건: 히터/보일러 + 고장/이상 → critical
        if ("히터" in text or "보일러" in text) and ("고장" in text or "작동" in text or "추운" in text):
            return "critical"
        # 물 공급 불가 → critical
        if "물" in text and ("전혀" in text or "없음" in text or "안 나" in text or "나오지 않" in text):
            return "critical"
        if any(kw in text for kw in _HIGH_KEYWORDS):
            return "high"
        if any(kw in text for kw in _LOW_KEYWORDS):
            return "low"
        return "medium"

    def _calc_confidence(self, text: str, category: str) -> float:
        if category == "기타":
            return 0.5
        for keywords, cat in _CATEGORY_RULES:
            if cat == category:
                matched = sum(1 for kw in keywords if kw in text)
                # 1개 매칭 = 0.85 (규칙 매칭은 충분히 신뢰)
                return min(0.75 + matched * 0.1, 1.0)
        return 0.5

    def _classify_with_llm(self, description: str) -> ClassificationResult:
        """LLM 폴백 분류"""
        llm = ChatOpenAI(model=settings.llm_model, temperature=0)
        prompt = f"""호텔 시설 관리 전문가로서 다음 결함 신고를 분류하세요.

신고 내용: {description}

다음 JSON 형식으로만 응답하세요:
{{
  "category": "전기|에어컨|배관|가구|청결|기타",
  "severity": "critical|high|medium|low",
  "confidence": 0.0~1.0,
  "reasoning": "판단 근거 한 문장"
}}

긴급도 기준:
- critical: 안전사고 위험(누전, 가스 누출), 투숙 불가 상태
- high: VIP 체크인 예정 객실, 당일 재판매 예정 객실
- medium: 투숙 중 객실의 일반 불편 사항
- low: 미입실 빈 객실, 예방 점검"""

        response = llm.invoke(prompt)
        raw = response.content.strip()
        # JSON 추출
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = json.loads(raw)

        return ClassificationResult(
            category=data.get("category", "기타"),
            severity=data.get("severity", "medium"),
            confidence=float(data.get("confidence", 0.9)),
            reasoning=data.get("reasoning", ""),
        )
