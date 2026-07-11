"""add provider credential pooling

Revision ID: c1f2a3b4d5e6
Revises: bd25b66f82e8
Create Date: 2026-07-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f2a3b4d5e6"
down_revision: str | Sequence[str] | None = "bd25b66f82e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("provider_credential", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("last_leased_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_provider_credential_provider_enabled", ["provider", "is_enabled"], unique=False)
        batch_op.create_index(
            "ix_provider_credential_provider_last_leased",
            ["provider", "last_leased_at", "id"],
            unique=False,
        )

    op.create_table(
        "provider_credential_lease",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["credential_id"], ["provider_credential.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("provider_credential_lease", schema=None) as batch_op:
        batch_op.create_index(
            "uq_provider_credential_lease_task_active",
            ["task_id"],
            unique=True,
            sqlite_where=sa.text("status = 'active'"),
            postgresql_where=sa.text("status = 'active'"),
        )
        batch_op.create_index(
            "ix_provider_credential_lease_provider_status_media",
            ["provider", "status", "media_type"],
            unique=False,
        )
        batch_op.create_index(
            "ix_provider_credential_lease_credential_status_media",
            ["credential_id", "status", "media_type"],
            unique=False,
        )
        batch_op.create_index("ix_provider_credential_lease_status_updated", ["status", "updated_at"], unique=False)

    op.create_table(
        "provider_job_binding",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_job_id", sa.String(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["credential_id"], ["provider_credential.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("provider_job_binding", schema=None) as batch_op:
        batch_op.create_index("uq_provider_job_binding_task", ["task_id"], unique=True)
        batch_op.create_index("ix_provider_job_binding_provider_job", ["provider", "provider_job_id"], unique=False)
        batch_op.create_index("ix_provider_job_binding_credential", ["credential_id", "media_type"], unique=False)

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("credential_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("wait_reason", sa.String(length=64), nullable=True))
        batch_op.create_index(
            "idx_tasks_status_provider_wait",
            ["status", "provider_id", "wait_reason", "queued_at"],
            unique=False,
        )
        batch_op.create_index("idx_tasks_credential_status", ["credential_id", "status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index("idx_tasks_credential_status")
        batch_op.drop_index("idx_tasks_status_provider_wait")
        batch_op.drop_column("wait_reason")
        batch_op.drop_column("credential_id")

    with op.batch_alter_table("provider_job_binding", schema=None) as batch_op:
        batch_op.drop_index("ix_provider_job_binding_credential")
        batch_op.drop_index("ix_provider_job_binding_provider_job")
        batch_op.drop_index("uq_provider_job_binding_task")
    op.drop_table("provider_job_binding")

    with op.batch_alter_table("provider_credential_lease", schema=None) as batch_op:
        batch_op.drop_index("ix_provider_credential_lease_status_updated")
        batch_op.drop_index("ix_provider_credential_lease_credential_status_media")
        batch_op.drop_index("ix_provider_credential_lease_provider_status_media")
        batch_op.drop_index("uq_provider_credential_lease_task_active")
    op.drop_table("provider_credential_lease")

    with op.batch_alter_table("provider_credential", schema=None) as batch_op:
        batch_op.drop_index("ix_provider_credential_provider_last_leased")
        batch_op.drop_index("ix_provider_credential_provider_enabled")
        batch_op.drop_column("last_leased_at")
        batch_op.drop_column("is_enabled")
