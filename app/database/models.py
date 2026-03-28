from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
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
