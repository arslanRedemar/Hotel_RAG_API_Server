"""SOP Export 단위 테스트"""

import pytest

from app.sop.export import export_checklist_csv, export_sop_to_pdf

SAMPLE_SOP = {
    "id": "test-id-123",
    "title": "체크인 표준 절차",
    "department_id": 1,
    "version": "1.0",
    "steps": [
        {"step_no": 1, "action": "고객 도착 시 인사", "responsible": "프런트", "duration_min": 2, "notes": "미소 유지"},
        {"step_no": 2, "action": "예약 확인", "responsible": None, "duration_min": None, "notes": None},
    ],
    "checklist_items": [
        {"text": "신분증 확인", "required": True},
        {"text": "결제 수단 등록", "required": True},
        {"text": "부가 서비스 안내", "required": False},
    ],
    "cautions": ["오버부킹 시 매니저 즉시 호출", "VIP 고객 특별 응대"],
    "updated_at": "2026-03-29T10:00:00",
}


class TestExportSOPToPDF:
    def test_returns_bytes(self):
        result = export_sop_to_pdf(SAMPLE_SOP)
        assert isinstance(result, bytes)

    def test_pdf_starts_with_magic_bytes(self):
        result = export_sop_to_pdf(SAMPLE_SOP)
        assert result[:4] == b"%PDF"

    def test_pdf_non_empty(self):
        result = export_sop_to_pdf(SAMPLE_SOP)
        assert len(result) > 500  # 최소 크기

    def test_empty_steps_does_not_raise(self):
        sop = {**SAMPLE_SOP, "steps": [], "checklist_items": [], "cautions": []}
        result = export_sop_to_pdf(sop)
        assert isinstance(result, bytes)

    def test_none_steps_does_not_raise(self):
        sop = {**SAMPLE_SOP, "steps": None, "checklist_items": None, "cautions": None}
        result = export_sop_to_pdf(sop)
        assert isinstance(result, bytes)


class TestExportChecklistCSV:
    def test_returns_string(self):
        result = export_checklist_csv(SAMPLE_SOP)
        assert isinstance(result, str)

    def test_contains_header(self):
        result = export_checklist_csv(SAMPLE_SOP)
        assert "번호" in result
        assert "항목" in result
        assert "필수여부" in result

    def test_contains_items(self):
        result = export_checklist_csv(SAMPLE_SOP)
        assert "신분증 확인" in result
        assert "결제 수단 등록" in result
        assert "부가 서비스 안내" in result

    def test_required_label(self):
        result = export_checklist_csv(SAMPLE_SOP)
        assert "필수" in result
        assert "선택" in result

    def test_empty_checklist_returns_header_only(self):
        sop = {**SAMPLE_SOP, "checklist_items": []}
        result = export_checklist_csv(sop)
        lines = [l for l in result.strip().splitlines() if l]
        assert len(lines) == 1  # 헤더만

    def test_row_count_matches_items(self):
        result = export_checklist_csv(SAMPLE_SOP)
        lines = [l for l in result.strip().splitlines() if l]
        assert len(lines) == 1 + len(SAMPLE_SOP["checklist_items"])  # 헤더 + 항목 수
