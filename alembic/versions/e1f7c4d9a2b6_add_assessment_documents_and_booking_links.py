"""add_assessment_documents_and_booking_links

Revision ID: e1f7c4d9a2b6
Revises: d3f1a9c4b2e1
Create Date: 2026-04-21 12:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1f7c4d9a2b6"
down_revision = "d3f1a9c4b2e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "assessment_documents" not in table_names:
        op.create_table(
            "assessment_documents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("symptom_name", sa.String(length=255), nullable=True),
            sa.Column("source_route", sa.String(length=255), nullable=True),
            sa.Column("intake_payload", sa.JSON(), nullable=False),
            sa.Column("ai_output", sa.JSON(), nullable=False),
            sa.Column("conversation_log", sa.JSON(), nullable=False),
            sa.Column(
                "status",
                sa.Enum("draft", "completed", name="assessment_document_status"),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_assessment_documents_user_id"), "assessment_documents", ["user_id"], unique=False)
        op.create_index(op.f("ix_assessment_documents_session_id"), "assessment_documents", ["session_id"], unique=True)
        op.create_index(op.f("ix_assessment_documents_status"), "assessment_documents", ["status"], unique=False)
        op.create_index(op.f("ix_assessment_documents_created_at"), "assessment_documents", ["created_at"], unique=False)

    booking_columns = {column["name"] for column in inspector.get_columns("bookings")}

    with op.batch_alter_table("bookings") as batch_op:
        if "linked_assessment_id" not in booking_columns:
            batch_op.add_column(
                sa.Column(
                    "linked_assessment_id",
                    sa.String(length=36),
                    sa.ForeignKey("assessment_documents.id", ondelete="SET NULL"),
                    nullable=True,
                )
            )
        if "provider_name" not in booking_columns:
            batch_op.add_column(sa.Column("provider_name", sa.String(length=255), nullable=True))
        if "provider_external_id" not in booking_columns:
            batch_op.add_column(sa.Column("provider_external_id", sa.String(length=120), nullable=True))
        if "location_name" not in booking_columns:
            batch_op.add_column(sa.Column("location_name", sa.String(length=255), nullable=True))
        if "location_address" not in booking_columns:
            batch_op.add_column(sa.Column("location_address", sa.Text(), nullable=True))

        batch_op.alter_column("doctor_id", existing_type=sa.String(length=36), nullable=True)
        batch_op.alter_column("hospital_id", existing_type=sa.String(length=36), nullable=True)

    booking_indexes = {index["name"] for index in inspector.get_indexes("bookings")}
    if "ix_bookings_linked_assessment_id" not in booking_indexes:
        op.create_index("ix_bookings_linked_assessment_id", "bookings", ["linked_assessment_id"], unique=False)
    if "ix_bookings_provider_external_id" not in booking_indexes:
        op.create_index("ix_bookings_provider_external_id", "bookings", ["provider_external_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    booking_columns = {column["name"] for column in inspector.get_columns("bookings")}
    booking_indexes = {index["name"] for index in inspector.get_indexes("bookings")}

    if "ix_bookings_provider_external_id" in booking_indexes:
        op.drop_index("ix_bookings_provider_external_id", table_name="bookings")
    if "ix_bookings_linked_assessment_id" in booking_indexes:
        op.drop_index("ix_bookings_linked_assessment_id", table_name="bookings")

    with op.batch_alter_table("bookings") as batch_op:
        if "location_address" in booking_columns:
            batch_op.drop_column("location_address")
        if "location_name" in booking_columns:
            batch_op.drop_column("location_name")
        if "provider_external_id" in booking_columns:
            batch_op.drop_column("provider_external_id")
        if "provider_name" in booking_columns:
            batch_op.drop_column("provider_name")
        if "linked_assessment_id" in booking_columns:
            batch_op.drop_column("linked_assessment_id")
        batch_op.alter_column("hospital_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.alter_column("doctor_id", existing_type=sa.String(length=36), nullable=False)

    table_names = set(inspector.get_table_names())
    if "assessment_documents" in table_names:
        op.drop_index(op.f("ix_assessment_documents_created_at"), table_name="assessment_documents")
        op.drop_index(op.f("ix_assessment_documents_status"), table_name="assessment_documents")
        op.drop_index(op.f("ix_assessment_documents_session_id"), table_name="assessment_documents")
        op.drop_index(op.f("ix_assessment_documents_user_id"), table_name="assessment_documents")
        op.drop_table("assessment_documents")
