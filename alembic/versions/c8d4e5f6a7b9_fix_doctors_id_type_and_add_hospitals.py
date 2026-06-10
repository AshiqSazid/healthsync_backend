"""fix_doctors_id_type_and_add_hospitals

Revision ID: c8d4e5f6a7b9
Revises: b7c2e8f9a3d1
Create Date: 2026-05-14 15:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'c8d4e5f6a7b9'
down_revision = 'b7c2e8f9a3d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    # 1) Convert doctors.id from INTEGER to VARCHAR(36)
    if "doctors" in table_names:
        id_type = ""
        for col in inspector.get_columns("doctors"):
            if col["name"] == "id":
                id_type = str(col["type"]).upper()
                break
        if "INTEGER" in id_type:
            op.execute(
                "ALTER TABLE doctors ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
            )

    # 2) Create hospitals table if missing
    if "hospitals" not in table_names:
        op.create_table(
            "hospitals",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("address", sa.String(length=255), nullable=False),
            sa.Column("city", sa.String(length=120), nullable=False),
            sa.Column("country", sa.String(length=120), nullable=False),
            sa.Column("pincode", sa.String(length=20), nullable=True),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("facilities", sa.JSON(), nullable=False),
            sa.Column("operating_hours", sa.JSON(), nullable=False),
            sa.Column("emergency_services", sa.Boolean(), nullable=False),
            sa.Column("departments", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_hospitals_name", "hospitals", ["name"], unique=False)
        op.create_index("ix_hospitals_city", "hospitals", ["city"], unique=False)
        op.create_index("ix_hospitals_created_at", "hospitals", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "hospitals" in table_names:
        for idx in ("ix_hospitals_name", "ix_hospitals_city", "ix_hospitals_created_at"):
            try:
                op.drop_index(idx, table_name="hospitals")
            except Exception:
                pass
        op.drop_table("hospitals")

    # Revert doctors.id back to INTEGER (best-effort; values must be numeric).
    if "doctors" in table_names:
        try:
            op.execute(
                "ALTER TABLE doctors ALTER COLUMN id TYPE INTEGER USING id::integer"
            )
        except Exception:
            pass
