"""Provider credential pooling ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin, utc_now


class ProviderCredentialLease(TimestampMixin, Base):
    """A short-lived lease that reserves one provider credential for a task."""

    __tablename__ = "provider_credential_lease"
    __table_args__ = (
        Index(
            "uq_provider_credential_lease_task_active",
            "task_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_provider_credential_lease_provider_status_media",
            "provider",
            "status",
            "media_type",
        ),
        Index(
            "ix_provider_credential_lease_credential_status_media",
            "credential_id",
            "status",
            "media_type",
        ),
        Index("ix_provider_credential_lease_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("provider_credential.id", ondelete="RESTRICT"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProviderJobBinding(TimestampMixin, Base):
    """Persistent binding from a provider job id to the credential used to submit it."""

    __tablename__ = "provider_job_binding"
    __table_args__ = (
        Index("uq_provider_job_binding_task", "task_id", unique=True),
        Index("ix_provider_job_binding_provider_job", "provider", "provider_job_id"),
        Index("ix_provider_job_binding_credential", "credential_id", "media_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_job_id: Mapped[str] = mapped_column(String, nullable=False)
    credential_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("provider_credential.id", ondelete="RESTRICT"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
