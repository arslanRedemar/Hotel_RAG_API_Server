"""SOP PDF/체크리스트 Export (SOP-F22)"""

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


def export_sop_to_pdf(sop: dict) -> bytes:
    """SOP를 A4 PDF 바이트로 변환 (reportlab)"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as e:
        raise RuntimeError("reportlab 미설치. pip install reportlab") from e

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
    italic_style = ParagraphStyle("italic", parent=styles["Normal"], fontName="Helvetica-Oblique")
    story = []

    # 제목
    story.append(Paragraph(sop.get("title", "SOP 문서"), styles["Title"]))
    meta = (
        f"부서: {sop.get('department_id', '-')} | "
        f"버전: {sop.get('version', '1.0')} | "
        f"최종 수정: {sop.get('updated_at', '-')}"
    )
    story.append(Paragraph(meta, styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    # 절차 단계
    steps = sop.get("steps") or []
    if steps:
        story.append(Paragraph("표준 절차", styles["Heading2"]))
        for step in steps:
            line = f"Step {step.get('step_no', '?')}. {step.get('action', '')}"
            if step.get("responsible"):
                line += f"  <i>(담당: {step['responsible']})</i>"
            if step.get("duration_min"):
                line += f"  [{step['duration_min']}분]"
            story.append(Paragraph(line, styles["Normal"]))
            if step.get("notes"):
                story.append(Paragraph(f"  → {step['notes']}", italic_style))
        story.append(Spacer(1, 0.3 * cm))

    # 체크리스트
    checklist = sop.get("checklist_items") or []
    if checklist:
        story.append(Paragraph("점검 체크리스트", styles["Heading2"]))
        for item in checklist:
            mark = " ★" if item.get("required") else ""
            story.append(Paragraph(f"□  {item.get('text', '')}{mark}", styles["Normal"]))
        story.append(Spacer(1, 0.3 * cm))

    # 주의사항
    cautions = sop.get("cautions") or []
    if cautions:
        story.append(Paragraph("주의사항", styles["Heading2"]))
        for c in cautions:
            story.append(Paragraph(f"⚠  {c}", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()


def export_checklist_csv(sop: dict) -> str:
    """체크리스트 항목을 CSV 문자열로 변환"""
    import csv
    import io as _io

    buf = _io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["번호", "항목", "필수여부"])
    for i, item in enumerate(sop.get("checklist_items") or [], start=1):
        if isinstance(item, dict):
            text = item.get("text", "")
            required = "필수" if item.get("required") else "선택"
        else:
            text = str(item)
            required = "선택"
        writer.writerow([i, text, required])
    return buf.getvalue()
