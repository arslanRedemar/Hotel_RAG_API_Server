"""Work Order 반복 고장 패턴 분석 (WO-F12)"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class PatternAnalyzer:
    """동일 객실+카테고리에서 반복 고장 감지"""

    def analyze(
        self,
        work_orders: list[dict],
        window_days: int = 90,
        min_count: int = 3,
    ) -> list[dict]:
        """
        Args:
            work_orders: WO dict 목록 (room_no, category, reported_at, id 포함)
            window_days: 분석 기간 (일)
            min_count: 반복 기준 최소 횟수
        Returns:
            패턴 목록 (count 내림차순 정렬)
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        groups: dict[tuple, list[dict]] = {}

        for wo in work_orders:
            reported_at = wo.get("reported_at")
            if not reported_at:
                continue
            if isinstance(reported_at, str):
                dt = datetime.fromisoformat(reported_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = reported_at

            if dt < cutoff:
                continue

            key = (wo.get("room_no", ""), wo.get("category", ""))
            groups.setdefault(key, []).append(wo)

        patterns = []
        for (room_no, category), items in groups.items():
            if len(items) < min_count:
                continue
            patterns.append({
                "room_no": room_no,
                "category": category,
                "count": len(items),
                "last_occurrence": max(w["reported_at"] for w in items),
                "work_order_ids": [w["id"] for w in items],
                "recommendation": (
                    f"{room_no}호 {category} 시스템 근본 점검 권고 "
                    f"({len(items)}회 반복 고장)"
                ),
            })

        return sorted(patterns, key=lambda x: x["count"], reverse=True)
