"""ensure_doctors_and_bookings_core_columns

Revision ID: 2fba286531f0
Revises: 8a734844a185
Create Date: 2026-05-14 10:36:00.390473

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '2fba286531f0'
down_revision = '8a734844a185'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "doctors" in table_names:
        doctor_columns = {column["name"] for column in inspector.get_columns("doctors")}
        doctor_indexes = {index["name"] for index in inspector.get_indexes("doctors")}
        doctor_foreign_keys = inspector.get_foreign_keys("doctors")
        has_user_fk = any(
            fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["user_id"]
            for fk in doctor_foreign_keys
        )

        if "sub_specializations" not in doctor_columns:
            op.add_column("doctors", sa.Column("sub_specializations", sa.JSON(), nullable=True))

        if "user_id" not in doctor_columns:
            op.add_column("doctors", sa.Column("user_id", sa.String(length=36), nullable=True))
            doctor_columns.add("user_id")

        if "user_id" in doctor_columns and not has_user_fk:
            op.create_foreign_key(
                "fk_doctors_user_id_users",
                "doctors",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )

        if "user_id" in doctor_columns and "ix_doctors_user_id" not in doctor_indexes:
            op.create_index("ix_doctors_user_id", "doctors", ["user_id"], unique=True)

    if "bookings" in table_names:
        booking_columns = {column["name"] for column in inspector.get_columns("bookings")}
        booking_indexes = {index["name"] for index in inspector.get_indexes("bookings")}
        booking_foreign_keys = inspector.get_foreign_keys("bookings")
        has_user_fk = any(
            fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["user_id"]
            for fk in booking_foreign_keys
        )

        if "user_id" not in booking_columns:
            op.add_column("bookings", sa.Column("user_id", sa.String(length=36), nullable=True))
            booking_columns.add("user_id")

        if "user_id" in booking_columns and not has_user_fk:
            op.create_foreign_key(
                "fk_bookings_user_id_users",
                "bookings",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )

        if "user_id" in booking_columns and "ix_bookings_user_id" not in booking_indexes:
            op.create_index("ix_bookings_user_id", "bookings", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "bookings" in table_names:
        booking_columns = {column["name"] for column in inspector.get_columns("bookings")}
        booking_indexes = {index["name"] for index in inspector.get_indexes("bookings")}
        booking_foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("bookings") if fk.get("name")}
        if "ix_bookings_user_id" in booking_indexes:
            op.drop_index("ix_bookings_user_id", table_name="bookings")
        if "fk_bookings_user_id_users" in booking_foreign_keys:
            op.drop_constraint("fk_bookings_user_id_users", "bookings", type_="foreignkey")
        if "user_id" in booking_columns:
            op.drop_column("bookings", "user_id")

    if "doctors" in table_names:
        doctor_columns = {column["name"] for column in inspector.get_columns("doctors")}
        doctor_indexes = {index["name"] for index in inspector.get_indexes("doctors")}
        doctor_foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("doctors") if fk.get("name")}
        if "ix_doctors_user_id" in doctor_indexes:
            op.drop_index("ix_doctors_user_id", table_name="doctors")
        if "fk_doctors_user_id_users" in doctor_foreign_keys:
            op.drop_constraint("fk_doctors_user_id_users", "doctors", type_="foreignkey")
        if "user_id" in doctor_columns:
            op.drop_column("doctors", "user_id")
        if "sub_specializations" in doctor_columns:
            op.drop_column("doctors", "sub_specializations")
