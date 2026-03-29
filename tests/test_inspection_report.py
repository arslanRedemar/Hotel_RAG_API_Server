"""InspectionReportGenerator 단위 테스트 (CA-F30~F32)"""

from unittest.mock import patch


from app.inspections.report_generator import InspectionReportGenerator


def _make_record(record_id: str, overall_result: str = "pass", ng_count: int = 0) -> dict:
    items = [{"item_id": f"item-{i}", "result": "OK", "note": None, "photo_url": None} for i in range(3)]
    if ng_count > 0:
        items[0] = {"item_id": "item-0", "result": "NG", "note": "불량 발견", "photo_url": None}
    return {
        "id": record_id,
        "template_id": "tpl-1",
        "location": "주방 A",
        "inspector_id": 1,
        "inspector_name": "박민수",
        "inspected_at": "2026-03-29T08:00:00",
        "submitted_at": "2026-03-29T08:30:00",
        "overall_result": overall_result,
        "ng_count": ng_count,
        "items": items,
        "signature": "박민수 | 2026-03-29T08:30:00",
    }


class TestCalculateSummary:
    def setup_method(self):
        self.gen = InspectionReportGenerator()

    def test_empty_records(self):
        summary = self.gen._calculate_summary([])
        assert summary["total_inspections"] == 0
        assert summary["pass_rate_pct"] == 0.0
        assert summary["ng_rate_pct"] == 0.0

    def test_all_pass(self):
        records = [_make_record(f"r{i}", "pass", 0) for i in range(5)]
        summary = self.gen._calculate_summary(records)
        assert summary["total_inspections"] == 5
        assert summary["pass_count"] == 5
        assert summary["fail_count"] == 0
        assert summary["pass_rate_pct"] == 100.0

    def test_mixed_results(self):
        records = [
            _make_record("r1", "pass", 0),
            _make_record("r2", "conditional_pass", 1),
            _make_record("r3", "fail", 3),
        ]
        summary = self.gen._calculate_summary(records)
        assert summary["pass_count"] == 1
        assert summary["conditional_pass_count"] == 1
        assert summary["fail_count"] == 1
        assert summary["total_ng_count"] == 4

    def test_ng_rate_calculated(self):
        records = [_make_record("r1", "conditional_pass", 1)]
        summary = self.gen._calculate_summary(records)
        # 3 items, 1 NG → ~33%
        assert summary["ng_rate_pct"] > 0

    def test_pass_rate_calculated(self):
        records = [
            _make_record("r1", "pass", 0),
            _make_record("r2", "fail", 3),
        ]
        summary = self.gen._calculate_summary(records)
        assert summary["pass_rate_pct"] == 50.0


class TestCollectNgItems:
    def setup_method(self):
        self.gen = InspectionReportGenerator()

    def test_no_ng_returns_empty(self):
        records = [_make_record("r1", "pass", 0)]
        ng_items = self.gen._collect_ng_items(records)
        assert ng_items == []

    def test_ng_item_extracted(self):
        records = [_make_record("r1", "conditional_pass", 1)]
        ng_items = self.gen._collect_ng_items(records)
        assert len(ng_items) == 1
        assert ng_items[0]["item_id"] == "item-0"
        assert ng_items[0]["note"] == "불량 발견"
        assert ng_items[0]["location"] == "주방 A"

    def test_multiple_ng_items(self):
        record = {
            "id": "r1",
            "location": "로비",
            "inspected_at": "2026-03-29T08:00:00",
            "overall_result": "fail",
            "ng_count": 2,
            "items": [
                {"item_id": "i-1", "result": "NG", "note": "불량1", "photo_url": None},
                {"item_id": "i-2", "result": "OK", "note": None, "photo_url": None},
                {"item_id": "i-3", "result": "NG", "note": "불량2", "photo_url": "http://img/1.jpg"},
            ],
        }
        ng_items = self.gen._collect_ng_items([record])
        assert len(ng_items) == 2
        assert {i["item_id"] for i in ng_items} == {"i-1", "i-3"}


class TestGenerate:
    def setup_method(self):
        self.gen = InspectionReportGenerator()

    def test_generate_returns_bytes(self):
        records = [_make_record("r1", "pass", 0)]
        filter_info = {"from_date": "2026-01-01", "to_date": "2026-03-29"}
        result = self.gen.generate(records, filter_info)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_generate_with_ng_items(self):
        records = [
            _make_record("r1", "pass", 0),
            _make_record("r2", "conditional_pass", 1),
        ]
        filter_info = {"from_date": "2026-01-01", "to_date": "2026-03-29", "types": ["위생"]}
        result = self.gen.generate(records, filter_info, hotel_name="테스트 호텔")
        assert isinstance(result, bytes)

    def test_generate_fallback_on_reportlab_error(self):
        records = [_make_record("r1", "pass", 0)]
        filter_info = {"from_date": "2026-01-01", "to_date": "2026-03-29"}

        with patch.object(self.gen, "_generate_with_reportlab", side_effect=Exception("reportlab error")):
            result = self.gen.generate(records, filter_info)

        assert isinstance(result, bytes)
        assert b"%PDF" in result

    def test_text_fallback_contains_summary(self):
        records = [_make_record("r1", "pass", 0)]
        filter_info = {"from_date": "2026-01-01", "to_date": "2026-03-29"}
        result = self.gen._generate_text_fallback(records, filter_info, hotel_name="Test Hotel")
        assert b"INSPECTION AUDIT REPORT" in result
        assert b"Test Hotel" in result

    def test_empty_records_generates_report(self):
        filter_info = {"from_date": "2026-01-01", "to_date": "2026-01-31"}
        result = self.gen.generate([], filter_info)
        assert isinstance(result, bytes)
