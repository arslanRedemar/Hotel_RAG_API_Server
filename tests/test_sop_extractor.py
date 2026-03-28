"""SOP Extractor 단위 테스트"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.sop.extractor import (
    SOPExtractor,
    calculate_extraction_confidence,
)


# ── calculate_extraction_confidence ──────────────────────────

class TestCalculateExtractionConfidence:
    def test_empty_result_gives_zero(self):
        score = calculate_extraction_confidence({}, "원문")
        assert score == 0.0

    def test_steps_gives_score(self):
        result = {"steps": [{"step_no": 1, "action": "10자 이상의 액션 문장입니다", "notes": None}]}
        score = calculate_extraction_confidence(result, "원문 텍스트")
        assert score >= 0.3

    def test_checklist_adds_score(self):
        result = {
            "steps": [{"step_no": 1, "action": "10자 이상의 액션 문장입니다", "notes": None}],
            "checklist_items": [{"text": "항목1", "required": True}],
        }
        without = calculate_extraction_confidence(
            {"steps": result["steps"]}, "원문"
        )
        with_checklist = calculate_extraction_confidence(result, "원문")
        assert with_checklist > without

    def test_max_is_one(self):
        result = {
            "title": "체크인 절차",
            "steps": [
                {"step_no": 1, "action": "고객에게 인사를 건네며 예약 확인을 요청합니다", "notes": "미소 유지"},
                {"step_no": 2, "action": "신분증을 확인하고 예약 정보를 조회합니다", "notes": None},
            ],
            "checklist_items": [{"text": "신분증 확인", "required": True}],
        }
        original = "체크인 절차 고객에게 인사를 건네며 예약 확인을 요청합니다 신분증을 확인하고"
        score = calculate_extraction_confidence(result, original)
        assert score <= 1.0

    def test_coverage_bonus(self):
        """추출 텍스트가 원문의 30% 이상이면 보너스 점수"""
        long_action = "이 액션은 매우 긴 텍스트를 포함합니다 " * 10
        result = {
            "steps": [{"step_no": 1, "action": long_action, "notes": long_action}],
        }
        short_original = "짧은 원문"
        score = calculate_extraction_confidence(result, short_original)
        assert score >= 0.4


# ── SOPExtractor.detect_document_type ────────────────────────

class TestDetectDocumentType:
    def setup_method(self):
        self.extractor = SOPExtractor.__new__(SOPExtractor)

    def test_detects_checklist(self):
        text = "□ 항목1\n□ 항목2\n□ 항목3\n□ 항목4\n□ 항목5\n□ 항목6"
        assert self.extractor.detect_document_type(text) == "checklist"

    def test_detects_procedure(self):
        text = "1. 도착 확인\n2. 예약 조회\n3. 신분증 확인\n4. 키 발급"
        assert self.extractor.detect_document_type(text) == "procedure"

    def test_defaults_to_manual(self):
        text = "일반적인 안내 문서입니다. 특별한 절차 없음."
        assert self.extractor.detect_document_type(text) == "manual"


# ── SOPExtractor.extract ─────────────────────────────────────

class TestSOPExtractorExtract:
    def _make_extractor_with_mock_llm(self, response_json: dict):
        extractor = SOPExtractor.__new__(SOPExtractor)
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(response_json)
        mock_llm.invoke.return_value = mock_response
        extractor.llm = mock_llm
        extractor.fallback_llm = None
        return extractor

    def test_returns_dict_with_required_keys(self):
        resp = {
            "title": "체크인 절차",
            "steps": [{"step_no": 1, "action": "고객에게 인사하세요 정중하게", "responsible": None, "duration_min": None, "notes": None}],
            "checklist_items": [],
            "cautions": [],
            "review_required": False,
            "extraction_confidence": 0.90,
        }
        extractor = self._make_extractor_with_mock_llm(resp)
        result = extractor.extract("1. 고객에게 인사하세요")
        assert "title" in result
        assert "steps" in result
        assert "checklist_items" in result
        assert "review_required" in result

    def test_sets_review_required_on_low_confidence(self):
        resp = {
            "title": "제목",
            "steps": [],
            "checklist_items": [],
            "cautions": [],
            "review_required": False,
            "extraction_confidence": 0.90,
        }
        extractor = self._make_extractor_with_mock_llm(resp)
        # 빈 steps → confidence 실제 계산 시 낮아짐
        result = extractor.extract("짧은 텍스트")
        # steps 없으니 계산 confidence = 0.0 < threshold → review_required=True
        assert result["review_required"] is True

    def test_uses_cloud_fallback_on_review_required(self):
        local_resp = {
            "title": "제목",
            "steps": [],
            "checklist_items": [],
            "cautions": [],
            "review_required": True,
            "extraction_confidence": 0.40,
        }
        cloud_resp = {
            "title": "클라우드 제목",
            "steps": [{"step_no": 1, "action": "클라우드 추출 액션 문장입니다", "responsible": None, "duration_min": None, "notes": None}],
            "checklist_items": [{"text": "항목", "required": True}],
            "cautions": [],
            "review_required": False,
            "extraction_confidence": 0.92,
        }
        extractor = SOPExtractor.__new__(SOPExtractor)

        mock_local = MagicMock()
        mock_local.invoke.return_value = MagicMock(content=json.dumps(local_resp))

        mock_cloud = MagicMock()
        mock_cloud.invoke.return_value = MagicMock(content=json.dumps(cloud_resp))

        extractor.llm = mock_local
        extractor.fallback_llm = mock_cloud

        result = extractor.extract("분석할 텍스트")

        mock_cloud.invoke.assert_called_once()
        assert result.get("_source") == "cloud_fallback"

    def test_json_parse_failure_returns_fallback(self):
        extractor = SOPExtractor.__new__(SOPExtractor)
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="이것은 JSON이 아닙니다")
        extractor.llm = mock_llm
        extractor.fallback_llm = None

        result = extractor.extract("텍스트")
        assert result["review_required"] is True
        assert result["extraction_confidence"] == 0.0

    def test_long_text_is_chunked(self):
        extractor = SOPExtractor.__new__(SOPExtractor)
        extractor.MAX_CHARS = 50
        extractor.CHUNK_OVERLAP = 10

        call_count = 0
        original_extract = SOPExtractor.extract

        def mock_extract(self_inner, text):
            nonlocal call_count
            if len(text) <= 50:
                call_count += 1
                return {
                    "title": f"청크{call_count}",
                    "steps": [{"step_no": 1, "action": "액션입니다 테스트용", "responsible": None, "duration_min": None, "notes": None}],
                    "checklist_items": [],
                    "cautions": ["주의사항"],
                    "review_required": False,
                    "extraction_confidence": 0.80,
                }
            return original_extract(self_inner, text)

        with patch.object(SOPExtractor, "extract", mock_extract):
            result = extractor._extract_chunked("A" * 200)

        assert result["review_required"] is True  # 분할 추출은 항상 True
        assert result["extraction_confidence"] == 0.65
