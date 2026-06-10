"""add_document_analysis_cache

Revision ID: b8d1c4f2e7a9
Revises: a4f7c1d2e9b3
Create Date: 2026-04-09 14:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8d1c4f2e7a9"
down_revision = "a4f7c1d2e9b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "document_analysis_cache" not in existing_tables:
        op.create_table(
            "document_analysis_cache",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("document_kind", sa.String(length=32), nullable=False),
            sa.Column("language", sa.String(length=8), nullable=False),
            sa.Column("vision_model", sa.String(length=64), nullable=False),
            sa.Column("prompt_version", sa.String(length=32), nullable=False),
            sa.Column("analysis_payload", sa.JSON(), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "content_hash",
                "document_kind",
                "language",
                "vision_model",
                "prompt_version",
                name="uq_document_analysis_cache_lookup",
            ),
        )

    existing_indexes = {
        index["name"] for index in inspector.get_indexes("document_analysis_cache")
    }

    for index_name, columns in [
        (op.f("ix_document_analysis_cache_content_hash"), ["content_hash"]),
        (op.f("ix_document_analysis_cache_document_kind"), ["document_kind"]),
        (op.f("ix_document_analysis_cache_language"), ["language"]),
        (op.f("ix_document_analysis_cache_vision_model"), ["vision_model"]),
        (op.f("ix_document_analysis_cache_prompt_version"), ["prompt_version"]),
        (op.f("ix_document_analysis_cache_created_at"), ["created_at"]),
        (op.f("ix_document_analysis_cache_last_accessed_at"), ["last_accessed_at"]),
    ]:
        if index_name not in existing_indexes:
            op.create_index(index_name, "document_analysis_cache", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "document_analysis_cache" not in inspector.get_table_names():
        return

    existing_indexes = {
        index["name"] for index in inspector.get_indexes("document_analysis_cache")
    }

    for index_name in [
        op.f("ix_document_analysis_cache_last_accessed_at"),
        op.f("ix_document_analysis_cache_created_at"),
        op.f("ix_document_analysis_cache_prompt_version"),
        op.f("ix_document_analysis_cache_vision_model"),
        op.f("ix_document_analysis_cache_language"),
        op.f("ix_document_analysis_cache_document_kind"),
        op.f("ix_document_analysis_cache_content_hash"),
    ]:
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="document_analysis_cache")

    op.drop_table("document_analysis_cache")
