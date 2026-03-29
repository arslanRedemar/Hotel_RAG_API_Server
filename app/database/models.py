from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base

# ─────────────────────────── 공통 ────────────────────────────


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="department")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("admin", "manager", "staff", name="user_role"),
        nullable=False,
        default="staff",
    )
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    skill_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    department: Mapped["Department | None"] = relationship(back_populates="users")


class AuditLog(Base):
    """불변 감사 로그 — DELETE 권한 없이 INSERT/SELECT만 허용."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    before_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )


class File(Base):
    """업로드 파일 메타데이터"""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PushSubscription(Base):
    """Web Push VAPID 구독 정보"""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(500), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ─────────────────────────── RAG ────────────────────────────


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class Document(Base):
    """RAG 인덱싱 대상 문서"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        Enum("pdf", "docx", "txt", name="doc_file_type"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    chroma_collection: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped["Document"] = relationship(back_populates="versions")


# ─────────────────────────── SOP ────────────────────────────


class SOP(Base):
    """SOP 디지털화 문서 (draft → active → archived)"""

    __tablename__ = "sops"

    from sqlalchemy import Numeric, UniqueConstraint

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(
        Enum("draft", "under_review", "active", "archived", name="sop_status"),
        nullable=False,
        default="draft",
        index=True,
    )
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    checklist_items: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cautions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extraction_confidence: Mapped[float | None] = mapped_column(
        "extraction_confidence", nullable=True
    )
    ocr_confidence: Mapped[float | None] = mapped_column("ocr_confidence", nullable=True)
    chroma_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    versions: Mapped[list["SOPVersionHistory"]] = relationship(back_populates="sop")
    acknowledgements: Mapped[list["SOPAcknowledgement"]] = relationship(back_populates="sop")


class SOPVersionHistory(Base):
    """SOP 버전 이력 스냅샷"""

    __tablename__ = "sop_version_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sop_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sop: Mapped["SOP"] = relationship(back_populates="versions")


class SOPAcknowledgement(Base):
    """SOP 확인(Acknowledge) 기록"""

    __tablename__ = "sop_acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sop_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    acked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sop: Mapped["SOP"] = relationship(back_populates="acknowledgements")


# ─────────────────────────── Work Order ──────────────────────


class WorkOrder(Base):
    """업무 지시서 (Work Order)"""

    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    wo_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    room_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    photo_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(
        Enum("critical", "high", "medium", "low"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        Enum("open", "assigned", "in_progress", "on_hold", "completed", "cancelled"),
        nullable=False,
        default="open",
        index=True,
    )
    ai_classification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reported_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    assigned_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    on_hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    parts_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    labor_hours: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    actual_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_contact: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    history: Mapped[list["WorkOrderHistory"]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan",
        order_by="WorkOrderHistory.changed_at",
    )
    reporter: Mapped["User"] = relationship(foreign_keys=[reported_by])
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])


class WorkOrderHistory(Base):
    """Work Order 상태 변경 이력"""

    __tablename__ = "work_order_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    work_order: Mapped["WorkOrder"] = relationship(back_populates="history")


class AssigneeCapability(Base):
    """담당자 역량 매핑 (어떤 유형을 처리할 수 있는지)"""

    __tablename__ = "assignee_capabilities"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(50), primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped["User"] = relationship()


# ─────────────────────── Compliance & Audit ──────────────────


class InspectionTemplate(Base):
    """점검 체크리스트 템플릿 (CA-F04)"""

    __tablename__ = "inspection_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    frequency_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    legal_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    schedules: Mapped[list["InspectionSchedule"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class InspectionSchedule(Base):
    """자동 생성된 점검 일정 (CA-F10)"""

    __tablename__ = "inspection_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inspection_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    assigned_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", index=True
    )
    notified_7d: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notified_1d: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    template: Mapped["InspectionTemplate"] = relationship(back_populates="schedules")


class InspectionRecord(Base):
    """점검 기록 — 제출 후 불변 (CA-F01~F03, CA-NF01)"""

    __tablename__ = "inspection_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("inspection_schedules.id", ondelete="SET NULL"), nullable=True
    )
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inspection_templates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    inspector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    inspector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    inspected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    overall_result: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    ng_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signature: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="mobile")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    template: Mapped["InspectionTemplate"] = relationship()
    corrective_actions: Mapped[list["InspectionCorrectiveAction"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class InspectionCorrectiveAction(Base):
    """NG 항목 조치 이력 (수정 가능, CA-F06)"""

    __tablename__ = "inspection_corrective_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inspection_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    work_order_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    completed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verification_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    record: Mapped["InspectionRecord"] = relationship(back_populates="corrective_actions")


# ─────────────────────── Revenue Management ──────────────────

from sqlalchemy import Date, UniqueConstraint  # noqa: E402


class DailyMetrics(Base):
    """일간 성과 지표 (PMS에서 수집)"""

    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[datetime] = mapped_column(Date, nullable=False, unique=True)
    total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    occupied_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    occupancy_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    adr: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    revpar: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    total_revenue: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    channel_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ota_commission: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReservationPickup(Base):
    """예약 픽업 이력 (수요 예측용)"""

    __tablename__ = "reservation_pickups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stay_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    confirmed_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    pickup_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    __table_args__ = (UniqueConstraint("stay_date", "snapshot_date", name="uq_stay_snapshot"),)


class CompetitorRate(Base):
    """경쟁사 요율 (일간 수집)"""

    __tablename__ = "competitor_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    stay_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    competitor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate_min: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    rate_max: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_soldout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    room_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LocalEvent(Base):
    """로컬 이벤트"""

    __tablename__ = "local_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expected_attendance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact_level: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", "very_high", name="event_impact"),
        nullable=False,
        default="medium",
    )
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RateRecommendation(Base):
    """AI 요율 권고"""

    __tablename__ = "rate_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    stay_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    recommended_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    current_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    rate_change_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    los_restriction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_taken: Mapped[str] = mapped_column(
        Enum("accepted", "modified", "rejected", "pending", name="rec_action"),
        nullable=False,
        default="pending",
    )
    actual_rate_applied: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DemandForecast(Base):
    """수요 예측 결과"""

    __tablename__ = "demand_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    stay_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    predicted_occupancy_base: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    predicted_occupancy_opt: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    predicted_occupancy_pess: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    actual_occupancy: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    mape: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    __table_args__ = (UniqueConstraint("forecast_date", "stay_date", name="uq_forecast_stay"),)


class GroupBookingSimulation(Base):
    """단체 예약 시뮬레이션 이력"""

    __tablename__ = "group_booking_simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rooms_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    check_in: Mapped[datetime] = mapped_column(Date, nullable=False)
    check_out: Mapped[datetime] = mapped_column(Date, nullable=False)
    proposed_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    simulated_accept_revenue: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    simulated_reject_revenue: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    opportunity_cost: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    recommendation: Mapped[str] = mapped_column(
        Enum("accept", "reject", "negotiate", name="group_rec"),
        nullable=False,
    )
    recommendation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
