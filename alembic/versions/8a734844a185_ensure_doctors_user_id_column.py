"""ensure_doctors_user_id_column

Revision ID: 8a734844a185
Revises: a7b9c3d4e5f6
Create Date: 2026-05-14 09:38:31.579177

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '8a734844a185'
down_revision = 'a7b9c3d4e5f6'
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
    doctor_foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("doctors") if fk.get("name")}

    if "user_id" not in doctor_columns:
        op.add_column("doctors", sa.Column("user_id", sa.String(length=36), nullable=True))

    doctor_columns = {column["name"] for column in inspect(bind).get_columns("doctors")}
    if "user_id" in doctor_columns and "fk_doctors_user_id_users" not in doctor_foreign_keys:
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


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "doctors" not in table_names:
        return

    doctor_columns = {column["name"] for column in inspector.get_columns("doctors")}
    doctor_indexes = {index["name"] for index in inspector.get_indexes("doctors")}
    doctor_foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("doctors") if fk.get("name")}

    if "ix_doctors_user_id" in doctor_indexes:
        op.drop_index("ix_doctors_user_id", table_name="doctors")

    if "fk_doctors_user_id_users" in doctor_foreign_keys:
        op.drop_constraint("fk_doctors_user_id_users", "doctors", type_="foreignkey")

    if "user_id" in doctor_columns:
        op.drop_column("doctors", "user_id")
