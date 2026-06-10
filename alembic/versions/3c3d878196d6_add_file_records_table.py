"""add_file_records_table

Revision ID: 3c3d878196d6
Revises: 9f0b3c1a2d4e
Create Date: 2026-03-12 22:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3c3d878196d6"
down_revision = "9f0b3c1a2d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("original_file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("storage_reference", sa.String(length=1000), nullable=False),
        sa.Column("file_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("upload_ip", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("UPLOADING", "CLEAN", "INFECTED", "ERROR", name="file_scan_status"),
            nullable=False,
        ),
        sa.Column("virus_scanned", sa.Boolean(), nullable=False),
        sa.Column("virus_found", sa.Boolean(), nullable=False),
        sa.Column("scan_result", sa.Text(), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_file_records_created_at"), "file_records", ["created_at"], unique=False)
    op.create_index(op.f("ix_file_records_file_hash"), "file_records", ["file_hash"], unique=False)
    op.create_index(op.f("ix_file_records_status"), "file_records", ["status"], unique=False)
    op.create_index(op.f("ix_file_records_user_id"), "file_records", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_file_records_user_id"), table_name="file_records")
    op.drop_index(op.f("ix_file_records_status"), table_name="file_records")
    op.drop_index(op.f("ix_file_records_file_hash"), table_name="file_records")
    op.drop_index(op.f("ix_file_records_created_at"), table_name="file_records")
    op.drop_table("file_records")
