import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BirthProfile(Base):
    __tablename__ = "birth_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alias: Mapped[str | None] = mapped_column(Text)
    birth_input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    has_birth_time: Mapped[bool]
    timezone: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('individual','couple')", name="ck_analysis_runs_mode"),
        CheckConstraint(
            "status IN ('PREPARED','VALIDATION_FAILED','FINALIZED','ABANDONED')",
            name="ck_analysis_runs_status",
        ),
        Index("ix_analysis_runs_participant_ids", "participant_ids", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(Text)
    participant_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot_hash: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="PREPARED", server_default="PREPARED")
    last_validation_errors: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ReportVersion(Base):
    __tablename__ = "report_versions"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_report_versions_version"),
        UniqueConstraint("report_id", "version", name="uq_report_versions_report_version"),
        UniqueConstraint(
            "analysis_id", "idempotency_key", name="uq_report_versions_analysis_idempotency"
        ),
        Index("ix_report_versions_type_created", "report_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id"))
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(Text)
    report_type: Mapped[str] = mapped_column(Text)
    body: Mapped[Any] = mapped_column(JSONB)
    markdown: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    validation: Mapped[Any] = mapped_column(JSONB)
    correction_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class AlternativeInterpretation(Base):
    __tablename__ = "alternative_interpretations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "report_version"],
            ["report_versions.report_id", "report_versions.version"],
            name="fk_alternatives_report_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    report_version: Mapped[int] = mapped_column(Integer)
    school: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
