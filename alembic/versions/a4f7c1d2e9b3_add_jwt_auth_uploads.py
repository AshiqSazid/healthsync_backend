"""add_jwt_auth_uploads

Revision ID: a4f7c1d2e9b3
Revises: 3c3d878196d6
Create Date: 2026-03-13 12:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a4f7c1d2e9b3"
down_revision = "3c3d878196d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_columns = {column["name"] for column in inspector.get_columns("users")}

    if "name" not in user_columns:
        op.add_column("users", sa.Column("name", sa.String(length=255), nullable=True))
    if "reset_token" not in user_columns:
        op.add_column("users", sa.Column("reset_token", sa.String(length=255), nullable=True))
    if "reset_token_expiry" not in user_columns:
        op.add_column("users", sa.Column("reset_token_expiry", sa.DateTime(timezone=True), nullable=True))
    if "refresh_token" not in user_columns:
        op.add_column("users", sa.Column("refresh_token", sa.String(length=255), nullable=True))

    op.execute("UPDATE users SET name = username WHERE name IS NULL")

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("name", existing_type=sa.String(length=255), nullable=False)

    existing_tables = set(inspector.get_table_names())
    if "uploads" not in existing_tables:
        op.create_table(
            "uploads",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column(
                "file_type",
                sa.Enum("PRESCRIPTION", "REPORT", name="upload_file_type"),
                nullable=False,
            ),
            sa.Column("cloudinary_public_id", sa.String(length=255), nullable=False),
            sa.Column("cloudinary_url", sa.String(length=1000), nullable=False),
            sa.Column("cloudinary_secure_url", sa.String(length=1000), nullable=False),
            sa.Column("original_filename", sa.String(length=255), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("mime_type", sa.String(length=255), nullable=False),
            sa.Column("folder_path", sa.String(length=500), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cloudinary_public_id"),
        )

    upload_indexes = {index["name"] for index in inspector.get_indexes("uploads")}
    if op.f("ix_uploads_file_type") not in upload_indexes:
        op.create_index(op.f("ix_uploads_file_type"), "uploads", ["file_type"], unique=False)
    if op.f("ix_uploads_uploaded_at") not in upload_indexes:
        op.create_index(op.f("ix_uploads_uploaded_at"), "uploads", ["uploaded_at"], unique=False)
    if op.f("ix_uploads_user_id") not in upload_indexes:
        op.create_index(op.f("ix_uploads_user_id"), "uploads", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "uploads" in inspector.get_table_names():
        upload_indexes = {index["name"] for index in inspector.get_indexes("uploads")}
        if op.f("ix_uploads_user_id") in upload_indexes:
            op.drop_index(op.f("ix_uploads_user_id"), table_name="uploads")
        if op.f("ix_uploads_uploaded_at") in upload_indexes:
            op.drop_index(op.f("ix_uploads_uploaded_at"), table_name="uploads")
        if op.f("ix_uploads_file_type") in upload_indexes:
            op.drop_index(op.f("ix_uploads_file_type"), table_name="uploads")
        op.drop_table("uploads")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    with op.batch_alter_table("users") as batch_op:
        if "refresh_token" in user_columns:
            batch_op.drop_column("refresh_token")
        if "reset_token_expiry" in user_columns:
            batch_op.drop_column("reset_token_expiry")
        if "reset_token" in user_columns:
            batch_op.drop_column("reset_token")
        if "name" in user_columns:
            batch_op.drop_column("name")
