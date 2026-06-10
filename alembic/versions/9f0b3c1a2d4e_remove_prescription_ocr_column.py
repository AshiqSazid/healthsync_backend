"""remove_prescription_ocr_column

Revision ID: 9f0b3c1a2d4e
Revises: fd8415973e9e
Create Date: 2026-03-12 16:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f0b3c1a2d4e"
down_revision = "fd8415973e9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prescriptions") as batch_op:
        batch_op.drop_column("ocr_text")


def downgrade() -> None:
    with op.batch_alter_table("prescriptions") as batch_op:
        batch_op.add_column(sa.Column("ocr_text", sa.Text(), nullable=True))
