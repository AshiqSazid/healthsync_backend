"""add_bookings_hospital_id

Revision ID: a1b2c3d4e5f6
Revises: 58e1e3cb2f54
Create Date: 2026-05-14 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'a1b2c3d4e5f6'
down_revision = '58e1e3cb2f54'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "bookings" not in table_names:
        return

    booking_columns = {col["name"] for col in inspector.get_columns("bookings")}
    booking_indexes = {idx["name"] for idx in inspector.get_indexes("bookings")}
    booking_fks = {fk.get("name") for fk in inspector.get_foreign_keys("bookings") if fk.get("name")}

    if "hospital_id" not in booking_columns:
        op.add_column("bookings", sa.Column("hospital_id", sa.String(length=36), nullable=True))

    if "ix_bookings_hospital_id" not in booking_indexes:
        op.create_index("ix_bookings_hospital_id", "bookings", ["hospital_id"], unique=False)

    if (
        "hospital_id" in booking_columns or "hospital_id" not in booking_columns
    ) and "hospitals" in table_names and "fk_bookings_hospital_id_hospitals" not in booking_fks:
        # Re-check column after possible add above
        booking_columns_now = {col["name"] for col in inspect(bind).get_columns("bookings")}
        if "hospital_id" in booking_columns_now:
            existing_fks = {fk.get("name") for fk in inspect(bind).get_foreign_keys("bookings") if fk.get("name")}
            if "fk_bookings_hospital_id_hospitals" not in existing_fks:
                op.create_foreign_key(
                    "fk_bookings_hospital_id_hospitals",
                    "bookings",
                    "hospitals",
                    ["hospital_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "bookings" not in table_names:
        return

    booking_fks = {fk.get("name") for fk in inspector.get_foreign_keys("bookings") if fk.get("name")}
    booking_indexes = {idx["name"] for idx in inspector.get_indexes("bookings")}
    booking_columns = {col["name"] for col in inspector.get_columns("bookings")}

    if "fk_bookings_hospital_id_hospitals" in booking_fks:
        op.drop_constraint("fk_bookings_hospital_id_hospitals", "bookings", type_="foreignkey")
    if "ix_bookings_hospital_id" in booking_indexes:
        op.drop_index("ix_bookings_hospital_id", table_name="bookings")
    if "hospital_id" in booking_columns:
        op.drop_column("bookings", "hospital_id")
