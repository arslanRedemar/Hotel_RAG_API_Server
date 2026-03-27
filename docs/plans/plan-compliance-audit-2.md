# Plan: Compliance & Audit — 이상 감지 / 보고서 생성 상세

> **상위 문서**: [plan-compliance-audit.md](./plan-compliance-audit.md)
> **내용**: 이상 패턴 감지 알고리즘, PDF 보고서 생성, 모바일 점검 UI

---

## 1. 이상 징후 자동 감지 (CA-F20~22)

### 1-1. 이상 감지 알고리즘

```python
# app/inspections/anomaly_detector.py

from datetime import datetime, timedelta
from collections import defaultdict, Counter

class AnomalyDetector:
    """
    감지 유형:
    A. 반복 NG 패턴 — 동일 항목이 N일 내 K회 이상 NG
    B. 구역 집중 이상 — 특정 층/구역에 NG 집중
    C. 점검 이탈 패턴 — 특정 담당자의 NG율 급변
    D. 에너지 이상 — 사용량 평균 대비 X% 급증 (CA-F22)
    """

    def detect_repeat_ng(self, template_id: str, item_id: str, days: int = 14) -> dict | None:
        """동일 항목이 14일 내 3회 이상 NG → 패턴 감지"""
        since = datetime.utcnow() - timedelta(days=days)
        records = get_inspection_records_by_template(template_id, since=since)

        ng_count = 0
        ng_records = []
        for record in records:
            for item in record["items"]:
                if item["item_id"] == item_id and item["result"] == "NG":
                    ng_count += 1
                    ng_records.append({
                        "record_id": record["id"],
                        "date": record["inspected_at"],
                        "note": item.get("note")
                    })

        if ng_count >= 3:
            template = get_template(template_id)
            item_def = get_template_item(template_id, item_id)
            return {
                "type": "repeat_ng",
                "severity": "high" if ng_count >= 5 else "medium",
                "template_id": template_id,
                "template_name": template["name"],
                "item_id": item_id,
                "item_description": item_def["description"],
                "ng_count": ng_count,
                "period_days": days,
                "occurrences": ng_records,
                "recommendation": f"'{item_def['description']}' 항목이 {days}일간 {ng_count}회 NG. 근본 원인 점검 및 SOP 재검토 필요."
            }
        return None

    def detect_zone_concentration(self, days: int = 7) -> list[dict]:
        """특정 구역(층, 구역)에 NG가 집중되는 경우 감지"""
        since = datetime.utcnow() - timedelta(days=days)
        records = get_all_recent_records(since=since)

        # (location, category) 기준 NG 집계
        zone_ng = defaultdict(lambda: {"count": 0, "records": []})
        for record in records:
            ng_items = [i for i in record["items"] if i["result"] == "NG"]
            if ng_items:
                key = record["location"]
                zone_ng[key]["count"] += len(ng_items)
                zone_ng[key]["records"].append(record["id"])

        # 전체 평균 대비 2배 이상인 구역 → 이상
        all_counts = [v["count"] for v in zone_ng.values() if v["count"] > 0]
        if not all_counts:
            return []
        avg_count = sum(all_counts) / len(all_counts)

        anomalies = []
        for location, data in zone_ng.items():
            if data["count"] >= 5 and data["count"] > avg_count * 2:
                anomalies.append({
                    "type": "zone_concentration",
                    "severity": "high",
                    "location": location,
                    "ng_count": data["count"],
                    "avg_count": round(avg_count, 1),
                    "record_ids": data["records"],
                    "recommendation": f"{location} 구역에서 {days}일간 NG {data['count']}건 집중 발생. 구조적 문제 점검 필요."
                })

        return anomalies

    def analyze_all(self, template_id: str = None) -> list[dict]:
        """전체 이상 패턴 종합 분석"""
        results = []

        templates = [get_template(template_id)] if template_id else get_active_templates()

        for template in templates:
            # 모든 항목에 대해 반복 NG 확인
            for item in template["items"]:
                pattern = self.detect_repeat_ng(template["id"], item["id"])
                if pattern:
                    results.append(pattern)

        # 구역 집중 이상 확인
        zone_anomalies = self.detect_zone_concentration()
        results.extend(zone_anomalies)

        return sorted(results, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]])
```

### 1-2. 이상 감지 자동 실행 (Celery)

```python
# app/tasks/inspection_tasks.py

@celery_app.task
def analyze_anomaly_patterns(template_id: str, location: str):
    """점검 기록 제출 후 비동기로 이상 패턴 분석 실행"""
    detector = AnomalyDetector()
    anomalies = detector.analyze_all(template_id=template_id)

    if anomalies:
        # 미발송 이상만 필터 (중복 알림 방지)
        new_anomalies = filter_unnotified_anomalies(anomalies)

        for anomaly in new_anomalies:
            # 관련 부서 관리자에게 알림
            template = get_template(anomaly.get("template_id"))
            dept_id = template["department_id"] if template else None

            if dept_id:
                NotificationService().notify_department_managers(
                    department_id=dept_id,
                    title=f"[이상 감지] {anomaly['type']} — {anomaly.get('location', anomaly.get('item_description', ''))}",
                    message=anomaly["recommendation"],
                    link="/inspections/anomalies"
                )

            # 이상 패턴 DB 기록
            save_anomaly_record(anomaly)

@celery_app.conf.beat_schedule.update({
    'daily-anomaly-analysis': {
        'task': 'app.tasks.inspection_tasks.full_anomaly_analysis',
        'schedule': crontab(hour=6, minute=0),  # 매일 06:00 전체 분석
    }
})

@celery_app.task
def full_anomaly_analysis():
    """매일 전체 이상 패턴 분석"""
    detector = AnomalyDetector()
    anomalies = detector.analyze_all()
    # ... 처리
```

---

## 2. 감사 보고서 PDF 생성 (CA-F30~32)

### 2-1. 보고서 생성 엔진

```python
# app/inspections/report_generator.py

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from io import BytesIO
from datetime import datetime

class InspectionReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        self.styles.add(ParagraphStyle(
            name='KorTitle',
            fontName='HeelvicaNeue',  # 한글 폰트 (Noto Sans CJK 등)
            fontSize=16,
            spaceAfter=12,
            textColor=colors.HexColor('#1e3a5f')
        ))
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            fontSize=12,
            fontName='HeelvicaNeue-Bold',
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor('#2563eb')
        ))

    def generate(
        self,
        records: list[dict],
        filter_info: dict,
        hotel_name: str = "호텔"
    ) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=2*cm,
            bottomMargin=2*cm,
            leftMargin=2.5*cm,
            rightMargin=2.5*cm
        )
        story = []

        # 표지
        story.extend(self._build_cover(hotel_name, filter_info))
        story.append(PageBreak())

        # 요약 통계
        summary = self._calculate_summary(records)
        story.extend(self._build_summary_section(summary))
        story.append(PageBreak())

        # 유형별 점검 결과
        story.extend(self._build_results_by_type(records))

        # NG 항목 상세 내역
        ng_items = self._collect_ng_items(records)
        if ng_items:
            story.append(PageBreak())
            story.extend(self._build_ng_detail_section(ng_items))

        doc.build(story, onFirstPage=self._add_header_footer, onLaterPages=self._add_header_footer)
        return buffer.getvalue()

    def _build_cover(self, hotel_name: str, filter_info: dict) -> list:
        return [
            Spacer(1, 3*cm),
            Paragraph(f"{hotel_name}", self.styles["KorTitle"]),
            Paragraph("점검 감사 보고서", self.styles["Title"]),
            Spacer(1, 1*cm),
            Paragraph(f"기간: {filter_info.get('from_date')} ~ {filter_info.get('to_date')}", self.styles["Normal"]),
            Paragraph(f"점검 유형: {filter_info.get('types', '전체')}", self.styles["Normal"]),
            Paragraph(f"생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}", self.styles["Normal"]),
        ]

    def _calculate_summary(self, records: list[dict]) -> dict:
        total = len(records)
        passed = sum(1 for r in records if r["overall_result"] == "pass")
        cond = sum(1 for r in records if r["overall_result"] == "conditional_pass")
        failed = sum(1 for r in records if r["overall_result"] == "fail")
        total_items = sum(len(r["items"]) for r in records)
        ng_items = sum(r["ng_count"] for r in records)

        return {
            "total_inspections": total,
            "pass_count": passed,
            "conditional_pass_count": cond,
            "fail_count": failed,
            "pass_rate_pct": round(passed / total * 100, 1) if total else 0,
            "total_items_checked": total_items,
            "total_ng_count": ng_items,
            "ng_rate_pct": round(ng_items / total_items * 100, 1) if total_items else 0,
        }

    def _build_summary_section(self, summary: dict) -> list:
        story = []
        story.append(Paragraph("전체 요약", self.styles["SectionHeader"]))

        data = [
            ["항목", "수치"],
            ["총 점검 횟수", f"{summary['total_inspections']}회"],
            ["합격", f"{summary['pass_count']}회 ({summary['pass_rate_pct']}%)"],
            ["조건부 합격", f"{summary['conditional_pass_count']}회"],
            ["불합격", f"{summary['fail_count']}회"],
            ["총 점검 항목 수", f"{summary['total_items_checked']}개"],
            ["NG 항목 수", f"{summary['total_ng_count']}개 ({summary['ng_rate_pct']}%)"],
        ]

        table = Table(data, colWidths=[8*cm, 8*cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "HeelvicaNeue"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ]))
        story.append(table)
        return story

    def _build_ng_detail_section(self, ng_items: list[dict]) -> list:
        story = [Paragraph("NG 항목 상세 내역", self.styles["SectionHeader"])]

        data = [["점검일", "위치", "항목", "비고", "조치 완료"]]
        for item in ng_items:
            data.append([
                item["inspected_at"][:10],
                item["location"],
                item["item_description"][:30],
                (item.get("note") or "")[:40],
                "✓" if item.get("corrective_action_completed") else "미완료"
            ])

        table = Table(data, colWidths=[2.5*cm, 3*cm, 5*cm, 4.5*cm, 2*cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#dc2626')),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(table)
        return story

    def _add_header_footer(self, canvas, doc):
        """모든 페이지에 헤더/푸터 추가"""
        canvas.saveState()
        # 푸터: 페이지 번호
        canvas.setFont("HeelvicaNeue", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(
            A4[0] - 2.5*cm,
            1.5*cm,
            f"페이지 {doc.page}"
        )
        canvas.restoreState()
```

### 2-2. 한글 폰트 설정

```python
# app/core/fonts.py (앱 시작 시 1회 실행)

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

def register_korean_fonts():
    """Noto Sans CJK 한글 폰트 등록"""
    font_dir = os.path.join(os.path.dirname(__file__), "../../assets/fonts")

    # 폰트 파일은 assets/fonts/에 배치
    pdfmetrics.registerFont(TTFont("HeelvicaNeue", f"{font_dir}/NotoSansCJKkr-Regular.otf"))
    pdfmetrics.registerFont(TTFont("HeelvicaNeue-Bold", f"{font_dir}/NotoSansCJKkr-Bold.otf"))

# main.py lifespan에서 호출
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    register_korean_fonts()   # 추가
    yield
```

### 2-3. 보고서 생성 API

```python
# app/api/routes/inspections.py

@router.post("/inspection-reports/generate")
async def generate_inspection_report(
    request: ReportRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db)
):
    """
    ReportRequest:
    - from_date: date
    - to_date: date
    - types: list[str] (위생/소방/안전/객실품질, 없으면 전체)
    - department_id: str | None
    - inspector_id: int | None
    """
    # 조건에 맞는 점검 기록 조회
    records = get_inspection_records_filtered(
        db=db,
        from_date=request.from_date,
        to_date=request.to_date,
        types=request.types,
        department_id=request.department_id,
        inspector_id=request.inspector_id,
        user=current_user  # 관리자 아니면 자기 부서만
    )

    if not records:
        raise HTTPException(status_code=404, detail="조건에 해당하는 점검 기록이 없습니다")

    # PDF 생성
    generator = InspectionReportGenerator()
    pdf_bytes = generator.generate(
        records=[r.to_dict() for r in records],
        filter_info=request.dict(),
        hotel_name=settings.hotel_name
    )

    # 파일명: inspection_report_20260327.pdf
    filename = f"inspection_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
```

---

## 3. 모바일 점검 UI (Next.js)

### 3-1. 점검 체크리스트 화면

```typescript
// components/inspection/ChecklistForm.tsx

interface ChecklistItem {
  id: string
  category: string
  description: string
  required: boolean
  photoRequiredOnNg: boolean
  legalRef?: string
  result?: 'OK' | 'NG' | 'NA'
  note?: string
  photoFile?: File
  photoUrl?: string
}

export function ChecklistForm({ template, schedule }: Props) {
  const [items, setItems] = useState<ChecklistItem[]>(
    template.items.map(item => ({ ...item, result: undefined }))
  )
  const [submitting, setSubmitting] = useState(false)

  const updateItem = (itemId: string, updates: Partial<ChecklistItem>) => {
    setItems(prev => prev.map(item =>
      item.id === itemId ? { ...item, ...updates } : item
    ))
  }

  const allRequired = items.filter(i => i.required)
  const completedRequired = allRequired.filter(i => i.result !== undefined)
  const progress = Math.round(completedRequired.length / allRequired.length * 100)

  return (
    <div className="max-w-2xl mx-auto p-4">
      {/* 진행률 */}
      <div className="sticky top-0 bg-white z-10 pb-3 border-b mb-4">
        <div className="flex justify-between text-sm text-gray-600 mb-1">
          <span>{template.name}</span>
          <span>{completedRequired.length}/{allRequired.length} 완료</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* 카테고리별 그루핑 */}
      {groupBy(items, 'category').map(([category, categoryItems]) => (
        <div key={category} className="mb-6">
          <h3 className="font-semibold text-gray-700 mb-3 border-l-4 border-blue-500 pl-2">
            {category}
          </h3>
          <div className="space-y-3">
            {categoryItems.map(item => (
              <ChecklistItemCard
                key={item.id}
                item={item}
                onUpdate={(updates) => updateItem(item.id, updates)}
              />
            ))}
          </div>
        </div>
      ))}

      {/* 제출 버튼 */}
      <button
        onClick={handleSubmit}
        disabled={submitting || completedRequired.length < allRequired.length}
        className="w-full py-4 bg-blue-600 text-white rounded-xl font-semibold disabled:opacity-50"
      >
        {submitting ? '제출 중...' : `점검 완료 제출 (${completedRequired.length}/${allRequired.length})`}
      </button>
    </div>
  )
}

function ChecklistItemCard({ item, onUpdate }: { item: ChecklistItem; onUpdate: (u: Partial<ChecklistItem>) => void }) {
  const isNG = item.result === 'NG'

  return (
    <div className={`border rounded-xl p-4 ${isNG ? 'border-red-300 bg-red-50' : 'border-gray-200'}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <p className="font-medium text-gray-800">{item.description}</p>
          {item.required && <span className="text-red-500 text-xs">★ 필수</span>}
          {item.legalRef && (
            <p className="text-gray-400 text-xs mt-0.5">{item.legalRef}</p>
          )}
        </div>
      </div>

      {/* OK / NG / N/A 버튼 */}
      <div className="flex gap-2">
        {(['OK', 'NG', 'NA'] as const).map(result => (
          <button
            key={result}
            onClick={() => onUpdate({ result, note: result !== 'NG' ? undefined : item.note })}
            className={`flex-1 py-2 rounded-lg font-semibold text-sm transition-all ${
              item.result === result
                ? result === 'OK' ? 'bg-green-500 text-white'
                  : result === 'NG' ? 'bg-red-500 text-white'
                  : 'bg-gray-400 text-white'
                : 'bg-gray-100 text-gray-600'
            }`}
          >
            {result === 'NA' ? '해당없음' : result}
          </button>
        ))}
      </div>

      {/* NG 선택 시 추가 입력 */}
      {isNG && (
        <div className="mt-3 space-y-2">
          <textarea
            placeholder="NG 비고 (필수)"
            value={item.note || ''}
            onChange={(e) => onUpdate({ note: e.target.value })}
            className="w-full border rounded-lg p-2 text-sm"
            rows={2}
          />
          {item.photoRequiredOnNg && (
            <div className="flex gap-2">
              <label className="flex-1 py-2 bg-gray-100 rounded-lg text-center text-sm cursor-pointer">
                📷 사진 촬영 (필수)
                <input type="file" accept="image/*" capture="environment" className="hidden"
                  onChange={(e) => onUpdate({ photoFile: e.target.files?.[0] })} />
              </label>
              {item.photoFile && (
                <div className="w-16 h-16 rounded-lg overflow-hidden">
                  <img src={URL.createObjectURL(item.photoFile)} className="w-full h-full object-cover" />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

---

## 4. 점검 일정 캘린더 UI (CA-F13)

```typescript
// components/inspection/ScheduleCalendar.tsx

export function ScheduleCalendar() {
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const { data: schedules } = useSchedules(currentMonth)

  const getStatusColor = (status: string) => ({
    completed: 'bg-green-500',
    scheduled: 'bg-blue-500',
    overdue: 'bg-red-500',
    in_progress: 'bg-yellow-500'
  })[status] || 'bg-gray-400'

  return (
    <div className="bg-white rounded-xl border p-4">
      <div className="flex justify-between items-center mb-4">
        <button onClick={() => setCurrentMonth(prev => subMonths(prev, 1))}>◀</button>
        <h2 className="font-semibold">{format(currentMonth, 'yyyy년 M월')}</h2>
        <button onClick={() => setCurrentMonth(prev => addMonths(prev, 1))}>▶</button>
      </div>

      <div className="grid grid-cols-7 gap-1">
        {/* 요일 헤더 */}
        {['월', '화', '수', '목', '금', '토', '일'].map(d => (
          <div key={d} className="text-center text-xs text-gray-500 py-1">{d}</div>
        ))}

        {/* 날짜 셀 */}
        {getDatesInMonth(currentMonth).map(date => {
          const daySchedules = schedules?.filter(s => isSameDay(parseISO(s.scheduled_date), date)) || []
          return (
            <div key={date.toISOString()} className="min-h-[60px] border rounded-lg p-1">
              <span className="text-xs text-gray-500">{format(date, 'd')}</span>
              <div className="mt-1 space-y-0.5">
                {daySchedules.slice(0, 3).map(s => (
                  <div key={s.id} className={`${getStatusColor(s.status)} text-white text-xs rounded px-1 truncate`}>
                    {s.template_name.slice(0, 6)}
                  </div>
                ))}
                {daySchedules.length > 3 && (
                  <div className="text-xs text-gray-400">+{daySchedules.length - 3}개</div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* 범례 */}
      <div className="flex gap-3 mt-3 text-xs text-gray-600">
        <div className="flex items-center gap-1"><div className="w-3 h-3 bg-green-500 rounded" /> 완료</div>
        <div className="flex items-center gap-1"><div className="w-3 h-3 bg-blue-500 rounded" /> 예정</div>
        <div className="flex items-center gap-1"><div className="w-3 h-3 bg-red-500 rounded" /> 지연</div>
      </div>
    </div>
  )
}
```
