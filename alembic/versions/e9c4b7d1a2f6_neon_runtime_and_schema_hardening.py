"""neon runtime and schema hardening

Revision ID: e9c4b7d1a2f6
Revises: d8f1a2b3c4d5
Create Date: 2026-05-14 11:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "e9c4b7d1a2f6"
down_revision = "d8f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "bookings" in table_names:
        booking_columns = {col["name"] for col in inspector.get_columns("bookings")}
        if "client_request_id" not in booking_columns:
            op.add_column("bookings", sa.Column("client_request_id", sa.String(length=64), nullable=True))
        booking_columns = {col["name"] for col in inspect(bind).get_columns("bookings")}
        if "client_request_id" in booking_columns:
            op.create_index("ix_bookings_client_request_id", "bookings", ["client_request_id"], unique=True)
        if {"status", "created_at"}.issubset(booking_columns):
            op.create_index("ix_bookings_status_created_at", "bookings", ["status", "created_at"], unique=False)

    if "document_analysis_cache" in table_names:
        cache_columns = {col["name"] for col in inspector.get_columns("document_analysis_cache")}
        if "expires_at" not in cache_columns:
            op.add_column("document_analysis_cache", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_document_analysis_cache_expires_at", "document_analysis_cache", ["expires_at"], unique=False)

    if "payments" in table_names and "payment_events" not in table_names:
        op.create_table(
            "payment_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("payment_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("event_source", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "payments" in table_names:
        op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"], unique=False)
        op.create_index("ix_payment_events_created_at", "payment_events", ["created_at"], unique=False)
        op.create_index("ix_payment_events_event_type", "payment_events", ["event_type"], unique=False)
        op.create_index(
            "ix_payment_events_payment_id_created_at",
            "payment_events",
            ["payment_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_payment_events_event_type_created_at",
            "payment_events",
            ["event_type", "created_at"],
            unique=False,
        )

    if "assessment_documents" in table_names and "assessment_document_payloads" not in table_names:
        op.create_table(
            "assessment_document_payloads",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("assessment_document_id", sa.String(length=36), nullable=False),
            sa.Column("intake_payload", sa.JSON(), nullable=False),
            sa.Column("ai_output", sa.JSON(), nullable=False),
            sa.Column("conversation_log", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["assessment_document_id"], ["assessment_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assessment_document_id"),
        )
    if "assessment_documents" in table_names:
        op.create_index(
            "ix_assessment_document_payloads_assessment_document_id",
            "assessment_document_payloads",
            ["assessment_document_id"],
            unique=True,
        )

    if "payments" in table_names:
        payment_columns = {col["name"] for col in inspector.get_columns("payments")}
        if {"status", "created_at"}.issubset(payment_columns):
            op.create_index("ix_payments_status_created_at", "payments", ["status", "created_at"], unique=False)
    if "symptom_checker_sessions" in table_names:
        session_columns = {col["name"] for col in inspector.get_columns("symptom_checker_sessions")}
        if {"status", "created_at"}.issubset(session_columns):
            op.create_index(
                "ix_symptom_sessions_status_created_at",
                "symptom_checker_sessions",
                ["status", "created_at"],
                unique=False,
            )

    if dialect == "postgresql" and "assessment_documents" in table_names:
        op.execute(
            """
            INSERT INTO assessment_document_payloads (
                id, assessment_document_id, intake_payload, ai_output, conversation_log, created_at, updated_at
            )
            SELECT
                md5(assessment_documents.id)::text,
                assessment_documents.id,
                COALESCE(assessment_documents.intake_payload, '{}'::json),
                COALESCE(assessment_documents.ai_output, '{}'::json),
                COALESCE(assessment_documents.conversation_log, '[]'::json),
                COALESCE(assessment_documents.created_at, NOW()),
                COALESCE(assessment_documents.updated_at, NOW())
            FROM assessment_documents
            WHERE NOT EXISTS (
                SELECT 1
                FROM assessment_document_payloads p
                WHERE p.assessment_document_id = assessment_documents.id
            )
            """
        )


def downgrade() -> None:
    for idx, tbl in [
        ("ix_symptom_sessions_status_created_at", "symptom_checker_sessions"),
        ("ix_payments_status_created_at", "payments"),
        ("ix_assessment_document_payloads_assessment_document_id", "assessment_document_payloads"),
        ("ix_payment_events_event_type_created_at", "payment_events"),
        ("ix_payment_events_payment_id_created_at", "payment_events"),
        ("ix_payment_events_event_type", "payment_events"),
        ("ix_payment_events_created_at", "payment_events"),
        ("ix_payment_events_payment_id", "payment_events"),
        ("ix_document_analysis_cache_expires_at", "document_analysis_cache"),
        ("ix_bookings_status_created_at", "bookings"),
        ("ix_bookings_client_request_id", "bookings"),
    ]:
        try:
            op.drop_index(idx, table_name=tbl)
        except Exception:
            pass

    for table_name in ["assessment_document_payloads", "payment_events"]:
        try:
            op.drop_table(table_name)
        except Exception:
            pass

    for table_name, column_name in [
        ("document_analysis_cache", "expires_at"),
        ("bookings", "client_request_id"),
    ]:
        try:
            op.drop_column(table_name, column_name)
        except Exception:
            pass
