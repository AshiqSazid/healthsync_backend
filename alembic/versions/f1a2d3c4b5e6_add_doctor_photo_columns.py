"""add doctor photo columns

Revision ID: f1a2d3c4b5e6
Revises: e9c4b7d1a2f6
Create Date: 2026-05-14 08:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f1a2d3c4b5e6"
down_revision = "e9c4b7d1a2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "doctors" not in table_names:
        return
    cols = {col["name"] for col in inspector.get_columns("doctors")}
    if "photo_url" not in cols:
        op.add_column("doctors", sa.Column("photo_url", sa.String(length=1000), nullable=True))
    if "photo_filename" not in cols:
        op.add_column("doctors", sa.Column("photo_filename", sa.String(length=255), nullable=True))


def downgrade() -> None:
    for col in ("photo_filename", "photo_url"):
        try:
            op.drop_column("doctors", col)
        except Exception:
            pass
