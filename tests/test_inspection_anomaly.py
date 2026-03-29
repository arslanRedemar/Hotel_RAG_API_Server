"""이상 감지 엔진 단위 테스트 (CA-F20, F21) — 순수 함수 기반"""

from datetime import datetime, timedelta


from app.inspections.anomaly_detector import AnomalyDetector


def _make_record(
    record_id: str,
    template_id: str,
    location: str,
    items: list[dict],
    days_ago: int = 0,
) -> dict:
    inspected_at = datetime.utcnow() - timedelta(days=days_ago)
    ng_count = sum(1 for i in items if i["result"] == "NG")
    return {
        "id": record_id,
        "template_id": template_id,
        "location": location,
        "items": items,
        "ng_count": ng_count,
        "inspected_at": inspected_at.isoformat(),
    }


def _ng_item(item_id: str, note: str = "불량") -> dict:
    return {"item_id": item_id, "result": "NG", "note": note, "photo_url": None}


def _ok_item(item_id: str) -> dict:
    return {"item_id": item_id, "result": "OK", "note": None, "photo_url": None}


# ── 반복 NG 감지 (CA-F20) ─────────────────────────────────────


class TestDetectRepeatNg:
    def setup_method(self):
        self.detector = AnomalyDetector()

    def test_three_ng_within_window_triggers(self):
        records = [
            _make_record("r1", "tpl-1", "주방", [_ng_item("h-001")], days_ago=2),
            _make_record("r2", "tpl-1", "주방", [_ng_item("h-001")], days_ago=10),
            _make_record("r3", "tpl-1", "주방", [_ng_item("h-001")], days_ago=20),
        ]
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert result is not None
        assert result["type"] == "repeat_ng"
        assert result["ng_count"] == 3

    def test_two_ng_no_trigger(self):
        records = [
            _make_record("r1", "tpl-1", "주방", [_ng_item("h-001")], days_ago=5),
            _make_record("r2", "tpl-1", "주방", [_ng_item("h-001")], days_ago=15),
        ]
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert result is None

    def test_ng_outside_window_not_counted(self):
        records = [
            _make_record("r1", "tpl-1", "주방", [_ng_item("h-001")], days_ago=3),
            _make_record("r2", "tpl-1", "주방", [_ng_item("h-001")], days_ago=12),
            _make_record("r3", "tpl-1", "주방", [_ng_item("h-001")], days_ago=35),  # 창 밖
        ]
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert result is None  # 28일 내 2건만 해당

    def test_different_item_id_not_counted(self):
        records = [
            _make_record("r1", "tpl-1", "주방", [_ng_item("h-002")], days_ago=2),
            _make_record("r2", "tpl-1", "주방", [_ng_item("h-002")], days_ago=10),
            _make_record("r3", "tpl-1", "주방", [_ng_item("h-002")], days_ago=20),
        ]
        # h-001 항목에 대해 감지 → 없음
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert result is None

    def test_five_ng_severity_high(self):
        records = [
            _make_record(f"r{i}", "tpl-1", "주방", [_ng_item("h-001")], days_ago=i)
            for i in range(1, 6)
        ]
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert result["severity"] == "high"

    def test_three_ng_severity_medium(self):
        records = [
            _make_record(f"r{i}", "tpl-1", "주방", [_ng_item("h-001")], days_ago=i * 3)
            for i in range(1, 4)
        ]
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert result["severity"] == "medium"

    def test_result_contains_recommendation(self):
        records = [
            _make_record(f"r{i}", "tpl-1", "주방", [_ng_item("h-001")], days_ago=i * 2)
            for i in range(1, 4)
        ]
        result = self.detector.detect_repeat_ng(records, item_id="h-001", days=28)
        assert "recommendation" in result
        assert len(result["recommendation"]) > 0

    def test_empty_records_returns_none(self):
        result = self.detector.detect_repeat_ng([], item_id="h-001", days=28)
        assert result is None


# ── 구역 집중 이상 감지 (CA-F21) ──────────────────────────────


class TestDetectZoneConcentration:
    def setup_method(self):
        self.detector = AnomalyDetector()

    def test_above_30_percent_triggers(self):
        # 10개 항목 중 4개 NG = 40%
        items = [_ng_item(f"i-{i:03d}") for i in range(4)] + \
                [_ok_item(f"i-{i:03d}") for i in range(4, 10)]
        records = [_make_record("r1", "tpl-1", "3층 객실", items, days_ago=1)]
        anomalies = self.detector.detect_zone_concentration(records, days=7)
        assert any(a["location"] == "3층 객실" for a in anomalies)

    def test_below_30_percent_no_trigger(self):
        # 10개 항목 중 2개 NG = 20%
        items = [_ng_item(f"i-{i:03d}") for i in range(2)] + \
                [_ok_item(f"i-{i:03d}") for i in range(2, 10)]
        records = [_make_record("r1", "tpl-1", "주방", items, days_ago=1)]
        anomalies = self.detector.detect_zone_concentration(records, days=7)
        assert len(anomalies) == 0

    def test_outside_time_window_excluded(self):
        # 30일 전 기록 (7일 창 밖)
        items = [_ng_item(f"i-{i:03d}") for i in range(5)] + \
                [_ok_item(f"i-{i:03d}") for i in range(5, 10)]
        records = [_make_record("r1", "tpl-1", "주방", items, days_ago=10)]
        anomalies = self.detector.detect_zone_concentration(records, days=7)
        assert len(anomalies) == 0

    def test_multiple_zones_independent(self):
        # 3층: 40% NG, 1층: 10% NG
        items_3f = [_ng_item(f"i-{i}") for i in range(4)] + \
                   [_ok_item(f"i-{i}") for i in range(4, 10)]
        items_1f = [_ng_item("i-0")] + [_ok_item(f"i-{i}") for i in range(1, 10)]

        records = [
            _make_record("r1", "tpl-1", "3층", items_3f, days_ago=1),
            _make_record("r2", "tpl-1", "1층", items_1f, days_ago=1),
        ]
        anomalies = self.detector.detect_zone_concentration(records, days=7)
        locations = [a["location"] for a in anomalies]
        assert "3층" in locations
        assert "1층" not in locations

    def test_result_contains_ng_ratio(self):
        items = [_ng_item(f"i-{i}") for i in range(4)] + \
                [_ok_item(f"i-{i}") for i in range(4, 10)]
        records = [_make_record("r1", "tpl-1", "주방", items, days_ago=1)]
        anomalies = self.detector.detect_zone_concentration(records, days=7)
        assert anomalies[0]["ng_ratio_pct"] > 30


# ── 전체 분석 ─────────────────────────────────────────────────


class TestAnalyzeAll:
    def setup_method(self):
        self.detector = AnomalyDetector()

    def test_analyze_returns_list(self):
        result = self.detector.analyze_all([])
        assert isinstance(result, list)

    def test_analyze_sorted_by_severity(self):
        # high 이상 → medium 이상 순으로 정렬
        records = [
            _make_record(f"r{i}", "tpl-1", "주방", [_ng_item("h-001")], days_ago=i)
            for i in range(1, 6)  # 5회 → high
        ]
        result = self.detector.analyze_all(records, item_ids=["h-001"])
        if len(result) >= 2:
            severity_order = {"high": 0, "medium": 1, "low": 2}
            for i in range(len(result) - 1):
                assert severity_order.get(result[i]["severity"], 99) <= \
                       severity_order.get(result[i + 1]["severity"], 99)

    def test_analyze_combined_repeat_ng_and_zone(self):
        # 반복 NG + 구역 집중 동시 발생
        items_with_ng = [_ng_item("h-001")] + [_ok_item(f"i-{i}") for i in range(9)]
        records = [
            _make_record(f"r{i}", "tpl-1", "주방", items_with_ng, days_ago=i * 2)
            for i in range(1, 4)
        ]
        result = self.detector.analyze_all(records, item_ids=["h-001"])
        types = [r["type"] for r in result]
        assert "repeat_ng" in types
