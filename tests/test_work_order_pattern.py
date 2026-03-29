"""Work Order 반복 고장 패턴 분석 테스트 (WO-F12)"""

from datetime import datetime, timedelta, timezone

import pytest

from app.work_order.pattern_analyzer import PatternAnalyzer


@pytest.fixture
def analyzer():
    return PatternAnalyzer()


def make_wo(room_no, category, days_ago=0):
    reported_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "id": f"wo-{room_no}-{days_ago}",
        "room_no": room_no,
        "category": category,
        "reported_at": reported_at.isoformat(),
        "status": "completed",
    }


class TestRepeatPatternDetection:
    def test_detects_three_repeat_faults(self, analyzer):
        wos = [
            make_wo("503", "전기", days_ago=5),
            make_wo("503", "전기", days_ago=30),
            make_wo("503", "전기", days_ago=60),
        ]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert len(patterns) == 1
        assert patterns[0]["room_no"] == "503"
        assert patterns[0]["category"] == "전기"
        assert patterns[0]["count"] == 3

    def test_no_pattern_below_threshold(self, analyzer):
        wos = [
            make_wo("101", "배관", days_ago=5),
            make_wo("101", "배관", days_ago=30),
        ]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert len(patterns) == 0

    def test_different_rooms_not_grouped(self, analyzer):
        wos = [
            make_wo("101", "전기", days_ago=5),
            make_wo("102", "전기", days_ago=10),
            make_wo("103", "전기", days_ago=15),
        ]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert len(patterns) == 0

    def test_different_categories_not_grouped(self, analyzer):
        wos = [
            make_wo("503", "전기", days_ago=5),
            make_wo("503", "배관", days_ago=10),
            make_wo("503", "에어컨", days_ago=15),
        ]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert len(patterns) == 0

    def test_pattern_outside_window_excluded(self, analyzer):
        wos = [
            make_wo("503", "전기", days_ago=5),
            make_wo("503", "전기", days_ago=30),
            make_wo("503", "전기", days_ago=100),  # 90일 밖
        ]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert len(patterns) == 0

    def test_pattern_includes_wo_id_list(self, analyzer):
        wos = [
            make_wo("601", "가구", days_ago=1),
            make_wo("601", "가구", days_ago=20),
            make_wo("601", "가구", days_ago=40),
        ]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert len(patterns[0]["work_order_ids"]) == 3

    def test_results_sorted_by_count_desc(self, analyzer):
        wos = (
            [make_wo("503", "전기", days_ago=i * 5) for i in range(5)]
            + [make_wo("201", "배관", days_ago=i * 7) for i in range(3)]
        )
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert patterns[0]["count"] >= patterns[-1]["count"]

    def test_pattern_has_recommendation(self, analyzer):
        wos = [make_wo("503", "전기", days_ago=i * 10) for i in range(3)]
        patterns = analyzer.analyze(wos, window_days=90, min_count=3)
        assert "recommendation" in patterns[0]
        assert len(patterns[0]["recommendation"]) > 0
