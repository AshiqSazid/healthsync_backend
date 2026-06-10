"""expand payments for shurjopay

Revision ID: c7a9e4f1b2d3
Revises: f2c8a1b7d9e4
Create Date: 2026-05-11 12:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7a9e4f1b2d3"
down_revision = "f2c8a1b7d9e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}

    with op.batch_alter_table("payments") as batch_op:
        if "user_id" not in payment_columns:
            batch_op.add_column(sa.Column("user_id", sa.String(length=36), nullable=True))
        if "customer_order_id" not in payment_columns:
            batch_op.add_column(sa.Column("customer_order_id", sa.String(length=120), nullable=True))
        if "gateway_transaction_id" not in payment_columns:
            batch_op.add_column(sa.Column("gateway_transaction_id", sa.String(length=120), nullable=True))
        if "bank_transaction_id" not in payment_columns:
            batch_op.add_column(sa.Column("bank_transaction_id", sa.String(length=120), nullable=True))
        if "checkout_url" not in payment_columns:
            batch_op.add_column(sa.Column("checkout_url", sa.Text(), nullable=True))
        if "payer_name" not in payment_columns:
            batch_op.add_column(sa.Column("payer_name", sa.String(length=255), nullable=True))
        if "payer_phone" not in payment_columns:
            batch_op.add_column(sa.Column("payer_phone", sa.String(length=30), nullable=True))
        if "payer_email" not in payment_columns:
            batch_op.add_column(sa.Column("payer_email", sa.String(length=255), nullable=True))
        if "status_message" not in payment_columns:
            batch_op.add_column(sa.Column("status_message", sa.Text(), nullable=True))
        if "raw_init_payload" not in payment_columns:
            batch_op.add_column(sa.Column("raw_init_payload", sa.JSON(), nullable=True))
        if "raw_init_response" not in payment_columns:
            batch_op.add_column(sa.Column("raw_init_response", sa.JSON(), nullable=True))
        if "raw_verify_response" not in payment_columns:
            batch_op.add_column(sa.Column("raw_verify_response", sa.JSON(), nullable=True))
        if "raw_ipn_payload" not in payment_columns:
            batch_op.add_column(sa.Column("raw_ipn_payload", sa.JSON(), nullable=True))
        if "updated_at" not in payment_columns:
            batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

        batch_op.alter_column("currency", existing_type=sa.String(length=10), server_default="BDT")
        batch_op.alter_column(
            "payment_method",
            existing_type=sa.Enum("CARD", "UPI", "WALLET", name="payment_method"),
            type_=sa.String(length=120),
            nullable=True,
        )

    if bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                """
                UPDATE payments
                SET user_id = (
                    SELECT bookings.user_id
                    FROM bookings
                    WHERE bookings.id = payments.booking_id
                )
                WHERE user_id IS NULL OR user_id = ''
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE payments
                SET user_id = bookings.user_id
                FROM bookings
                WHERE bookings.id = payments.booking_id
                  AND (payments.user_id IS NULL OR payments.user_id = '')
                """
            )
        )
    op.execute(sa.text("UPDATE payments SET currency = COALESCE(NULLIF(currency, ''), 'BDT')"))
    op.execute(sa.text("UPDATE payments SET payment_gateway = COALESCE(NULLIF(payment_gateway, ''), 'shurjopay')"))
    op.execute(sa.text("UPDATE payments SET updated_at = COALESCE(updated_at, created_at)"))

    with op.batch_alter_table("payments") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_foreign_key("fk_payments_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")

    if "ix_payments_user_id" not in payment_indexes:
        op.create_index("ix_payments_user_id", "payments", ["user_id"], unique=False)
    if "ix_payments_customer_order_id" not in payment_indexes:
        op.create_index("ix_payments_customer_order_id", "payments", ["customer_order_id"], unique=True)
    if "ix_payments_gateway_transaction_id" not in payment_indexes:
        op.create_index("ix_payments_gateway_transaction_id", "payments", ["gateway_transaction_id"], unique=True)
    if "ix_payments_bank_transaction_id" not in payment_indexes:
        op.create_index("ix_payments_bank_transaction_id", "payments", ["bank_transaction_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    payment_columns = {column["name"] for column in inspector.get_columns("payments")}
    payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("payments")}

    if "ix_payments_bank_transaction_id" in payment_indexes:
        op.drop_index("ix_payments_bank_transaction_id", table_name="payments")
    if "ix_payments_gateway_transaction_id" in payment_indexes:
        op.drop_index("ix_payments_gateway_transaction_id", table_name="payments")
    if "ix_payments_customer_order_id" in payment_indexes:
        op.drop_index("ix_payments_customer_order_id", table_name="payments")
    if "ix_payments_user_id" in payment_indexes:
        op.drop_index("ix_payments_user_id", table_name="payments")

    with op.batch_alter_table("payments") as batch_op:
        if "fk_payments_user_id_users" in foreign_keys:
            batch_op.drop_constraint("fk_payments_user_id_users", type_="foreignkey")

        batch_op.alter_column(
            "payment_method",
            existing_type=sa.String(length=120),
            type_=sa.Enum("CARD", "UPI", "WALLET", name="payment_method"),
            nullable=False,
        )
        batch_op.alter_column("currency", existing_type=sa.String(length=10), server_default=None)

        if "updated_at" in payment_columns:
            batch_op.drop_column("updated_at")
        if "raw_ipn_payload" in payment_columns:
            batch_op.drop_column("raw_ipn_payload")
        if "raw_verify_response" in payment_columns:
            batch_op.drop_column("raw_verify_response")
        if "raw_init_response" in payment_columns:
            batch_op.drop_column("raw_init_response")
        if "raw_init_payload" in payment_columns:
            batch_op.drop_column("raw_init_payload")
        if "status_message" in payment_columns:
            batch_op.drop_column("status_message")
        if "payer_email" in payment_columns:
            batch_op.drop_column("payer_email")
        if "payer_phone" in payment_columns:
            batch_op.drop_column("payer_phone")
        if "payer_name" in payment_columns:
            batch_op.drop_column("payer_name")
        if "checkout_url" in payment_columns:
            batch_op.drop_column("checkout_url")
        if "bank_transaction_id" in payment_columns:
            batch_op.drop_column("bank_transaction_id")
        if "gateway_transaction_id" in payment_columns:
            batch_op.drop_column("gateway_transaction_id")
        if "customer_order_id" in payment_columns:
            batch_op.drop_column("customer_order_id")
        if "user_id" in payment_columns:
            batch_op.drop_column("user_id")
