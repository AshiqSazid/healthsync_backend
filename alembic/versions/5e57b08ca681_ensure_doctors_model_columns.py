"""ensure_doctors_model_columns

Revision ID: 5e57b08ca681
Revises: 2fba286531f0
Create Date: 2026-05-14 10:48:25.576727

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '5e57b08ca681'
down_revision = '2fba286531f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "doctors" not in table_names:
        return

    doctor_columns = {column["name"] for column in inspector.get_columns("doctors")}
    doctor_indexes = {index["name"] for index in inspector.get_indexes("doctors")}
    doctor_foreign_keys = inspector.get_foreign_keys("doctors")
    has_user_fk = any(
        fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["user_id"]
        for fk in doctor_foreign_keys
    )

    if "user_id" not in doctor_columns:
        op.add_column("doctors", sa.Column("user_id", sa.String(length=36), nullable=True))
        doctor_columns.add("user_id")
    if "specialization" not in doctor_columns:
        op.add_column("doctors", sa.Column("specialization", sa.JSON(), nullable=True))
    if "sub_specializations" not in doctor_columns:
        op.add_column("doctors", sa.Column("sub_specializations", sa.JSON(), nullable=True))
    if "license_number" not in doctor_columns:
        op.add_column("doctors", sa.Column("license_number", sa.String(length=120), nullable=True))

    if "user_id" in doctor_columns and not has_user_fk:
        op.create_foreign_key(
            "fk_doctors_user_id_users",
            "doctors",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if "ix_doctors_user_id" not in doctor_indexes:
        op.create_index("ix_doctors_user_id", "doctors", ["user_id"], unique=True)
    if "ix_doctors_license_number" not in doctor_indexes:
        op.create_index("ix_doctors_license_number", "doctors", ["license_number"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "doctors" not in table_names:
        return

    doctor_columns = {column["name"] for column in inspector.get_columns("doctors")}
    doctor_indexes = {index["name"] for index in inspector.get_indexes("doctors")}
    doctor_foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("doctors") if fk.get("name")}

    if "ix_doctors_license_number" in doctor_indexes:
        op.drop_index("ix_doctors_license_number", table_name="doctors")
    if "ix_doctors_user_id" in doctor_indexes:
        op.drop_index("ix_doctors_user_id", table_name="doctors")
    if "fk_doctors_user_id_users" in doctor_foreign_keys:
        op.drop_constraint("fk_doctors_user_id_users", "doctors", type_="foreignkey")

    for column_name in ("license_number", "sub_specializations", "specialization", "user_id"):
        if column_name in doctor_columns:
            op.drop_column("doctors", column_name)
