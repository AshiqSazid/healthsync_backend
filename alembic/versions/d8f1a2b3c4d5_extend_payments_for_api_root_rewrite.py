"""extend payments for api-root rewrite

Revision ID: d8f1a2b3c4d5
Revises: c7a9e4f1b2d3
Create Date: 2026-05-11 14:30:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8f1a2b3c4d5"
down_revision = "c7a9e4f1b2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'cancelled'")

    with op.batch_alter_table("payments") as batch_op:
        if "payable_amount" not in payment_columns:
            batch_op.add_column(sa.Column("payable_amount", sa.Numeric(10, 2), nullable=True))
        if "discount_amount" not in payment_columns:
            batch_op.add_column(sa.Column("discount_amount", sa.Numeric(10, 2), nullable=True))
        if "received_amount" not in payment_columns:
            batch_op.add_column(sa.Column("received_amount", sa.Numeric(10, 2), nullable=True))
        if "customer_address" not in payment_columns:
            batch_op.add_column(sa.Column("customer_address", sa.Text(), nullable=True))
        if "customer_city" not in payment_columns:
            batch_op.add_column(sa.Column("customer_city", sa.String(length=120), nullable=True))
        if "service_type" not in payment_columns:
            batch_op.add_column(sa.Column("service_type", sa.String(length=120), nullable=True))
        if "service_details" not in payment_columns:
            batch_op.add_column(sa.Column("service_details", sa.JSON(), nullable=True))
        if "bank_status" not in payment_columns:
            batch_op.add_column(sa.Column("bank_status", sa.String(length=120), nullable=True))
        if "sp_code" not in payment_columns:
            batch_op.add_column(sa.Column("sp_code", sa.Integer(), nullable=True))
        if "sp_message" not in payment_columns:
            batch_op.add_column(sa.Column("sp_message", sa.Text(), nullable=True))
        if "transaction_date" not in payment_columns:
            batch_op.add_column(sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=True))
        if "verified_at" not in payment_columns:
            batch_op.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(sa.text("UPDATE payments SET payable_amount = COALESCE(payable_amount, amount)"))
    op.execute(sa.text("UPDATE payments SET discount_amount = COALESCE(discount_amount, 0)"))
    op.execute(sa.text("UPDATE payments SET service_type = COALESCE(NULLIF(service_type, ''), 'doctor_booking')"))
    op.execute(sa.text("UPDATE payments SET sp_message = COALESCE(sp_message, status_message)"))
    op.execute(sa.text("UPDATE payments SET transaction_date = COALESCE(transaction_date, paid_at)"))
    op.execute(
        sa.text(
            """
            UPDATE payments
            SET received_amount = COALESCE(received_amount, amount)
            WHERE lower(status::text) = 'completed'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE payments
            SET verified_at = COALESCE(verified_at, paid_at, updated_at)
            WHERE raw_verify_response IS NOT NULL
            """
        )
    )

    if "ix_payments_transaction_date" not in payment_indexes:
        op.create_index("ix_payments_transaction_date", "payments", ["transaction_date"], unique=False)
    if "ix_payments_verified_at" not in payment_indexes:
        op.create_index("ix_payments_verified_at", "payments", ["verified_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}

    if "ix_payments_verified_at" in payment_indexes:
        op.drop_index("ix_payments_verified_at", table_name="payments")
    if "ix_payments_transaction_date" in payment_indexes:
        op.drop_index("ix_payments_transaction_date", table_name="payments")

    with op.batch_alter_table("payments") as batch_op:
        if "verified_at" in payment_columns:
            batch_op.drop_column("verified_at")
        if "transaction_date" in payment_columns:
            batch_op.drop_column("transaction_date")
        if "sp_message" in payment_columns:
            batch_op.drop_column("sp_message")
        if "sp_code" in payment_columns:
            batch_op.drop_column("sp_code")
        if "bank_status" in payment_columns:
            batch_op.drop_column("bank_status")
        if "service_details" in payment_columns:
            batch_op.drop_column("service_details")
        if "service_type" in payment_columns:
            batch_op.drop_column("service_type")
        if "customer_city" in payment_columns:
            batch_op.drop_column("customer_city")
        if "customer_address" in payment_columns:
            batch_op.drop_column("customer_address")
        if "received_amount" in payment_columns:
            batch_op.drop_column("received_amount")
        if "discount_amount" in payment_columns:
            batch_op.drop_column("discount_amount")
        if "payable_amount" in payment_columns:
            batch_op.drop_column("payable_amount")
