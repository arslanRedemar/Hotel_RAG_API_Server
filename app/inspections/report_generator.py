"""감사 보고서 PDF 생성기 (CA-F30~F32)"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)


class InspectionReportGenerator:
    """점검 기록을 PDF 바이트로 변환 — reportlab 사용"""

    def generate(
        self,
        records: list[dict],
        filter_info: dict,
        hotel_name: str = "Hotel AX",
    ) -> bytes:
        """점검 기록 리스트를 PDF로 생성하여 바이트 반환"""
        try:
            return self._generate_with_reportlab(records, filter_info, hotel_name)
        except Exception as exc:
            logger.warning("reportlab PDF 생성 실패 (%s), 텍스트 폴백 사용", exc)
            return self._generate_text_fallback(records, filter_info, hotel_name)

    def _generate_with_reportlab(
        self, records: list[dict], filter_info: dict, hotel_name: str
    ) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            leftMargin=2.5 * cm,
            rightMargin=2.5 * cm,
        )
        styles = getSampleStyleSheet()
        story = []

        # 표지
        story.append(Paragraph(f"{hotel_name} - Inspection Audit Report", styles["Title"]))
        story.append(Spacer(1, 0.5 * cm))
        from_date = filter_info.get("from_date", "")
        to_date = filter_info.get("to_date", "")
        story.append(Paragraph(f"Period: {from_date} ~ {to_date}", styles["Normal"]))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
        story.append(Spacer(1, 1 * cm))

        # 요약 통계
        summary = self._calculate_summary(records)
        story.append(Paragraph("Summary", styles["Heading2"]))
        summary_data = [
            ["Metric", "Value"],
            ["Total Inspections", str(summary["total_inspections"])],
            ["Pass", f"{summary['pass_count']} ({summary['pass_rate_pct']}%)"],
            ["Conditional Pass", str(summary["conditional_pass_count"])],
            ["Fail", str(summary["fail_count"])],
            ["Total NG Items", f"{summary['total_ng_count']} ({summary['ng_rate_pct']}%)"],
        ]
        tbl = Table(summary_data, colWidths=[8 * cm, 8 * cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 1 * cm))

        # NG 항목 상세
        ng_items = self._collect_ng_items(records)
        if ng_items:
            story.append(Paragraph("NG Item Details", styles["Heading2"]))
            ng_data = [["Date", "Location", "Item", "Note"]]
            for item in ng_items[:50]:  # 최대 50건
                ng_data.append([
                    item.get("inspected_at", "")[:10],
                    item.get("location", "")[:20],
                    item.get("item_id", "")[:20],
                    (item.get("note") or "")[:40],
                ])
            ng_tbl = Table(ng_data, colWidths=[2.5 * cm, 4 * cm, 4.5 * cm, 7 * cm])
            ng_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dc2626")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            story.append(ng_tbl)

        doc.build(story)
        return buffer.getvalue()

    def _generate_text_fallback(
        self, records: list[dict], filter_info: dict, hotel_name: str
    ) -> bytes:
        """reportlab 없을 때 최소 PDF 바이트 반환"""
        summary = self._calculate_summary(records)
        text = (
            f"INSPECTION AUDIT REPORT — {hotel_name}\n"
            f"Period: {filter_info.get('from_date', '')} ~ {filter_info.get('to_date', '')}\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Total Inspections: {summary['total_inspections']}\n"
            f"Pass: {summary['pass_count']} ({summary['pass_rate_pct']}%)\n"
            f"Fail: {summary['fail_count']}\n"
            f"Total NG: {summary['total_ng_count']} ({summary['ng_rate_pct']}%)\n"
        )
        # 최소한의 PDF 포맷으로 감싸기
        pdf_content = (
            b"%PDF-1.4\n"
            + b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            + text.encode("utf-8")
        )
        return pdf_content

    def _calculate_summary(self, records: list[dict]) -> dict:
        total = len(records)
        pass_count = sum(1 for r in records if r.get("overall_result") == "pass")
        cond_count = sum(1 for r in records if r.get("overall_result") == "conditional_pass")
        fail_count = sum(1 for r in records if r.get("overall_result") == "fail")
        total_items = sum(len(r.get("items", [])) for r in records)
        total_ng = sum(r.get("ng_count", 0) for r in records)
        return {
            "total_inspections": total,
            "pass_count": pass_count,
            "conditional_pass_count": cond_count,
            "fail_count": fail_count,
            "pass_rate_pct": round(pass_count / total * 100, 1) if total else 0.0,
            "total_items_checked": total_items,
            "total_ng_count": total_ng,
            "ng_rate_pct": round(total_ng / total_items * 100, 1) if total_items else 0.0,
        }

    def _collect_ng_items(self, records: list[dict]) -> list[dict]:
        ng_items = []
        for record in records:
            for item in record.get("items", []):
                if item.get("result") == "NG":
                    ng_items.append({
                        "inspected_at": record.get("inspected_at", ""),
                        "location": record.get("location", ""),
                        "item_id": item.get("item_id", ""),
                        "note": item.get("note"),
                        "photo_url": item.get("photo_url"),
                    })
        return ng_items
