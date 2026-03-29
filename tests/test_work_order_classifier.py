"""Work Order AI 분류 엔진 테스트 (WO-F10, F11, F14)"""

from unittest.mock import MagicMock, patch

import pytest

from app.work_order.classifier import ClassificationResult, WorkOrderClassifier


# ── 픽스처 ──────────────────────────────────────────────────


@pytest.fixture
def classifier():
    return WorkOrderClassifier()


# ── WO-F10: 카테고리 분류 ────────────────────────────────────


class TestCategoryClassification:
    CASES = [
        ("전구가 나갔습니다", "전기"),
        ("에어컨이 작동하지 않습니다", "에어컨"),
        ("변기가 막혔습니다", "배관"),
        ("침대 프레임이 흔들립니다", "가구"),
        ("욕실이 더럽습니다", "청결"),
        ("모르겠음", "기타"),
    ]

    @pytest.mark.parametrize("description,expected_category", CASES)
    def test_rule_based_classification(self, classifier, description, expected_category):
        result = classifier.classify_with_rules(description)
        assert result.category == expected_category

    def test_returns_classification_result_dataclass(self, classifier):
        result = classifier.classify_with_rules("전구 교체 필요")
        assert isinstance(result, ClassificationResult)
        assert result.category is not None
        assert result.severity is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_six_valid_categories(self, classifier):
        valid = {"전기", "에어컨", "배관", "가구", "청결", "기타"}
        result = classifier.classify_with_rules("테스트 신고")
        assert result.category in valid


# ── WO-F11: 긴급도 판단 ──────────────────────────────────────


class TestSeverityClassification:
    CRITICAL_CASES = [
        "누전이 발생했습니다. 불꽃이 튑니다",
        "가스 냄새가 납니다",
        "물이 전혀 나오지 않습니다",
        "히터가 완전히 고장났습니다. 매우 추운 상태",
    ]
    LOW_CASES = [
        "빈 객실 전구 교체 필요",
        "예방 점검 요청",
        "미입실 객실 소파 쿠션 교체",
    ]

    @pytest.mark.parametrize("description", CRITICAL_CASES)
    def test_critical_severity_detection(self, classifier, description):
        result = classifier.classify_with_rules(description)
        assert result.severity == "critical", f"'{description}' → critical 이어야 함"

    @pytest.mark.parametrize("description", LOW_CASES)
    def test_low_severity_detection(self, classifier, description):
        result = classifier.classify_with_rules(description)
        assert result.severity == "low", f"'{description}' → low 이어야 함"

    def test_severity_enum_values(self, classifier):
        valid = {"critical", "high", "medium", "low"}
        result = classifier.classify_with_rules("일반 신고")
        assert result.severity in valid


# ── WO-F14: 로컬 우선 + 클라우드 폴백 ──────────────────────


class TestLocalFirstFallback:
    def test_high_confidence_uses_rules_only(self, classifier):
        """명확한 키워드 → 클라우드 호출 없음"""
        with patch.object(classifier, "_classify_with_llm") as mock_llm:
            result = classifier.classify("전구가 나갔습니다")
            mock_llm.assert_not_called()
        assert result.category == "전기"

    def test_low_confidence_falls_back_to_llm(self, classifier):
        """모호한 표현 → LLM 폴백"""
        mock_result = ClassificationResult(
            category="전기", severity="medium", confidence=0.9
        )
        with patch.object(classifier, "_classify_with_llm", return_value=mock_result) as mock_llm:
            # confidence 임계값(0.8) 미만이 되도록 강제
            with patch.object(classifier, "classify_with_rules") as mock_rules:
                mock_rules.return_value = ClassificationResult(
                    category="기타", severity="medium", confidence=0.5
                )
                classifier.classify("뭔가 이상합니다")
                mock_llm.assert_called_once()

    def test_confidence_threshold_is_configurable(self, classifier):
        assert hasattr(classifier, "confidence_threshold")
        assert classifier.confidence_threshold == 0.8

    def test_llm_classify_calls_openai(self, classifier):
        with patch("app.work_order.classifier.ChatOpenAI") as mock_cls:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = MagicMock(
                content='{"category":"전기","severity":"medium","confidence":0.9,"reasoning":"테스트"}'
            )
            mock_cls.return_value = mock_llm
            result = classifier._classify_with_llm("전선이 조금 이상한 것 같습니다")
            assert result.category in {"전기", "에어컨", "배관", "가구", "청결", "기타"}
