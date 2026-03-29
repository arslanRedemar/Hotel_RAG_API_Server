"""이상 징후 자동 감지 엔진 (CA-F20, CA-F21) — 순수 함수 기반"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    감지 유형:
    A. 반복 NG — 동일 항목이 N일 내 K회 이상 NG (CA-F20)
    B. 구역 집중 — 특정 구역의 NG 비율 30% 초과 (CA-F21)
    """

    def detect_repeat_ng(
        self,
        records: list[dict],
        item_id: str,
        days: int = 28,
        min_count: int = 3,
    ) -> Optional[dict]:
        """동일 항목이 days일 내 min_count회 이상 NG → 패턴 반환 (CA-F20)"""
        cutoff = datetime.utcnow() - timedelta(days=days)

        ng_occurrences = []
        for record in records:
            try:
                inspected_at = datetime.fromisoformat(record["inspected_at"].replace("Z", "+00:00"))
                if inspected_at.tzinfo is not None:
                    inspected_at = inspected_at.replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            if inspected_at < cutoff:
                continue

            for item in record.get("items", []):
                if item.get("item_id") == item_id and item.get("result") == "NG":
                    ng_occurrences.append({
                        "record_id": record["id"],
                        "date": record["inspected_at"],
                        "note": item.get("note"),
                    })

        ng_count = len(ng_occurrences)
        if ng_count < min_count:
            return None

        severity = "high" if ng_count >= 5 else "medium"
        return {
            "type": "repeat_ng",
            "severity": severity,
            "item_id": item_id,
            "ng_count": ng_count,
            "period_days": days,
            "occurrences": ng_occurrences,
            "recommendation": (
                f"항목 '{item_id}'이(가) {days}일간 {ng_count}회 NG 발생. "
                "근본 원인 점검 및 SOP 재검토 필요."
            ),
        }

    def detect_zone_concentration(
        self,
        records: list[dict],
        days: int = 7,
        threshold: float = 0.30,
    ) -> list[dict]:
        """특정 구역 NG 비율이 threshold 초과 시 이상 패턴 반환 (CA-F21)"""
        cutoff = datetime.utcnow() - timedelta(days=days)

        zone_ng: dict[str, int] = defaultdict(int)
        zone_total: dict[str, int] = defaultdict(int)

        for record in records:
            try:
                inspected_at = datetime.fromisoformat(record["inspected_at"].replace("Z", "+00:00"))
                if inspected_at.tzinfo is not None:
                    inspected_at = inspected_at.replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            if inspected_at < cutoff:
                continue

            location = record.get("location", "unknown")
            items = record.get("items", [])
            zone_total[location] += len(items)
            zone_ng[location] += sum(1 for i in items if i.get("result") == "NG")

        anomalies = []
        for location, ng_count in zone_ng.items():
            total = zone_total[location]
            if total == 0:
                continue
            ratio = ng_count / total
            if ratio > threshold:
                anomalies.append({
                    "type": "zone_concentration",
                    "severity": "high",
                    "location": location,
                    "ng_count": ng_count,
                    "total_items": total,
                    "ng_ratio_pct": round(ratio * 100, 1),
                    "recommendation": (
                        f"{location} 구역에서 {days}일간 NG {ng_count}건 집중 발생 "
                        f"({round(ratio * 100, 1)}%). 구조적 문제 점검 필요."
                    ),
                })

        return anomalies

    def analyze_all(
        self,
        records: list[dict],
        item_ids: Optional[list[str]] = None,
        repeat_ng_days: int = 28,
        zone_days: int = 7,
    ) -> list[dict]:
        """전체 이상 패턴 종합 분석 — severity 순 정렬"""
        results: list[dict] = []

        # 반복 NG 분석
        if item_ids:
            for item_id in item_ids:
                pattern = self.detect_repeat_ng(records, item_id, days=repeat_ng_days)
                if pattern:
                    results.append(pattern)
        else:
            # item_ids 미지정 시 records에서 모든 item_id 수집
            all_item_ids: set[str] = set()
            for record in records:
                for item in record.get("items", []):
                    if item.get("item_id"):
                        all_item_ids.add(item["item_id"])
            for item_id in all_item_ids:
                pattern = self.detect_repeat_ng(records, item_id, days=repeat_ng_days)
                if pattern:
                    results.append(pattern)

        # 구역 집중 분석
        zone_anomalies = self.detect_zone_concentration(records, days=zone_days)
        results.extend(zone_anomalies)

        # severity 순 정렬 (high → medium → low)
        severity_order = {"high": 0, "medium": 1, "low": 2}
        results.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 99))
        return results
