"""create missing operational tables on legacy neon schemas

Revision ID: a7b9c3d4e5f6
Revises: f1a2d3c4b5e6
Create Date: 2026-05-14 09:05:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "a7b9c3d4e5f6"
down_revision = "f1a2d3c4b5e6"
branch_labels = None
depends_on = None


def _create_postgres_enum_if_missing(enum_name: str, labels: list[str]) -> None:
    labels_sql = ", ".join(f"'{label}'" for label in labels)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{enum_name}') THEN
                CREATE TYPE {enum_name} AS ENUM ({labels_sql});
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    dialect = bind.dialect.name

    if dialect == "postgresql":
        _create_postgres_enum_if_missing(
            "payment_status", ["pending", "completed", "failed", "cancelled", "refunded"]
        )
        _create_postgres_enum_if_missing("assessment_document_status", ["draft", "completed"])

    if "payments" not in table_names:
        op.create_table(
            "payments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("booking_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("payable_amount", sa.Numeric(10, 2), nullable=True),
            sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00")),
            sa.Column("received_amount", sa.Numeric(10, 2), nullable=True),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default="BDT"),
            sa.Column("payment_method", sa.String(length=120), nullable=True),
            sa.Column("transaction_id", sa.String(length=120), nullable=True),
            sa.Column("payment_gateway", sa.String(length=120), nullable=True),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "pending",
                    "completed",
                    "failed",
                    "cancelled",
                    "refunded",
                    name="payment_status",
                    create_type=False,
                ),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("customer_order_id", sa.String(length=120), nullable=True),
            sa.Column("gateway_transaction_id", sa.String(length=120), nullable=True),
            sa.Column("bank_transaction_id", sa.String(length=120), nullable=True),
            sa.Column("checkout_url", sa.Text(), nullable=True),
            sa.Column("payer_name", sa.String(length=255), nullable=True),
            sa.Column("payer_phone", sa.String(length=30), nullable=True),
            sa.Column("payer_email", sa.String(length=255), nullable=True),
            sa.Column("customer_address", sa.Text(), nullable=True),
            sa.Column("customer_city", sa.String(length=120), nullable=True),
            sa.Column("service_type", sa.String(length=120), nullable=True),
            sa.Column("service_details", sa.JSON(), nullable=True),
            sa.Column("bank_status", sa.String(length=120), nullable=True),
            sa.Column("sp_code", sa.Integer(), nullable=True),
            sa.Column("sp_message", sa.Text(), nullable=True),
            sa.Column("status_message", sa.Text(), nullable=True),
            sa.Column("raw_init_payload", sa.JSON(), nullable=True),
            sa.Column("raw_init_response", sa.JSON(), nullable=True),
            sa.Column("raw_verify_response", sa.JSON(), nullable=True),
            sa.Column("raw_ipn_payload", sa.JSON(), nullable=True),
            sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_payments_booking_id", "payments", ["booking_id"], unique=True)
        op.create_index("ix_payments_user_id", "payments", ["user_id"], unique=False)
        op.create_index("ix_payments_status", "payments", ["status"], unique=False)
        op.create_index("ix_payments_status_created_at", "payments", ["status", "created_at"], unique=False)
        op.create_index("ix_payments_customer_order_id", "payments", ["customer_order_id"], unique=True)
        op.create_index("ix_payments_gateway_transaction_id", "payments", ["gateway_transaction_id"], unique=True)
        op.create_index("ix_payments_transaction_date", "payments", ["transaction_date"], unique=False)
        op.create_index("ix_payments_verified_at", "payments", ["verified_at"], unique=False)
        op.create_index("ix_payments_paid_at", "payments", ["paid_at"], unique=False)

    table_names = set(inspect(bind).get_table_names())
    if "payment_events" not in table_names:
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

    table_names = set(inspect(bind).get_table_names())
    if "assessment_documents" not in table_names:
        op.create_table(
            "assessment_documents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("symptom_name", sa.String(length=255), nullable=True),
            sa.Column("source_route", sa.String(length=255), nullable=True),
            sa.Column("intake_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("ai_output", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("conversation_log", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column(
                "status",
                postgresql.ENUM("draft", "completed", name="assessment_document_status", create_type=False),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id"),
        )
        op.create_index("ix_assessment_documents_user_id", "assessment_documents", ["user_id"], unique=False)
        op.create_index("ix_assessment_documents_status", "assessment_documents", ["status"], unique=False)
        op.create_index("ix_assessment_documents_created_at", "assessment_documents", ["created_at"], unique=False)

    table_names = set(inspect(bind).get_table_names())
    if "assessment_document_payloads" not in table_names:
        op.create_table(
            "assessment_document_payloads",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("assessment_document_id", sa.String(length=36), nullable=False),
            sa.Column("intake_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("ai_output", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("conversation_log", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["assessment_document_id"], ["assessment_documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assessment_document_id"),
        )
        op.create_index(
            "ix_assessment_document_payloads_assessment_document_id",
            "assessment_document_payloads",
            ["assessment_document_id"],
            unique=True,
        )

    table_names = set(inspect(bind).get_table_names())
    if "document_analysis_cache" not in table_names:
        op.create_table(
            "document_analysis_cache",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("document_kind", sa.String(length=32), nullable=False),
            sa.Column("language", sa.String(length=8), nullable=False),
            sa.Column("vision_model", sa.String(length=64), nullable=False),
            sa.Column("prompt_version", sa.String(length=32), nullable=False, server_default="v1"),
            sa.Column("analysis_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "content_hash",
                "document_kind",
                "language",
                "vision_model",
                "prompt_version",
                name="uq_document_analysis_cache_lookup",
            ),
        )
        op.create_index("ix_document_analysis_cache_content_hash", "document_analysis_cache", ["content_hash"], unique=False)
        op.create_index("ix_document_analysis_cache_document_kind", "document_analysis_cache", ["document_kind"], unique=False)
        op.create_index("ix_document_analysis_cache_language", "document_analysis_cache", ["language"], unique=False)
        op.create_index("ix_document_analysis_cache_vision_model", "document_analysis_cache", ["vision_model"], unique=False)
        op.create_index("ix_document_analysis_cache_prompt_version", "document_analysis_cache", ["prompt_version"], unique=False)
        op.create_index("ix_document_analysis_cache_created_at", "document_analysis_cache", ["created_at"], unique=False)
        op.create_index("ix_document_analysis_cache_last_accessed_at", "document_analysis_cache", ["last_accessed_at"], unique=False)
        op.create_index("ix_document_analysis_cache_expires_at", "document_analysis_cache", ["expires_at"], unique=False)


def downgrade() -> None:
    for index_name, table_name in [
        ("ix_document_analysis_cache_expires_at", "document_analysis_cache"),
        ("ix_document_analysis_cache_last_accessed_at", "document_analysis_cache"),
        ("ix_document_analysis_cache_created_at", "document_analysis_cache"),
        ("ix_document_analysis_cache_prompt_version", "document_analysis_cache"),
        ("ix_document_analysis_cache_vision_model", "document_analysis_cache"),
        ("ix_document_analysis_cache_language", "document_analysis_cache"),
        ("ix_document_analysis_cache_document_kind", "document_analysis_cache"),
        ("ix_document_analysis_cache_content_hash", "document_analysis_cache"),
        ("ix_assessment_document_payloads_assessment_document_id", "assessment_document_payloads"),
        ("ix_assessment_documents_created_at", "assessment_documents"),
        ("ix_assessment_documents_status", "assessment_documents"),
        ("ix_assessment_documents_user_id", "assessment_documents"),
        ("ix_payment_events_event_type_created_at", "payment_events"),
        ("ix_payment_events_payment_id_created_at", "payment_events"),
        ("ix_payment_events_event_type", "payment_events"),
        ("ix_payment_events_created_at", "payment_events"),
        ("ix_payment_events_payment_id", "payment_events"),
        ("ix_payments_paid_at", "payments"),
        ("ix_payments_verified_at", "payments"),
        ("ix_payments_transaction_date", "payments"),
        ("ix_payments_gateway_transaction_id", "payments"),
        ("ix_payments_customer_order_id", "payments"),
        ("ix_payments_status_created_at", "payments"),
        ("ix_payments_status", "payments"),
        ("ix_payments_user_id", "payments"),
        ("ix_payments_booking_id", "payments"),
    ]:
        try:
            op.drop_index(index_name, table_name=table_name)
        except Exception:
            pass

    for table_name in [
        "document_analysis_cache",
        "assessment_document_payloads",
        "assessment_documents",
        "payment_events",
        "payments",
    ]:
        try:
            op.drop_table(table_name)
        except Exception:
            pass
