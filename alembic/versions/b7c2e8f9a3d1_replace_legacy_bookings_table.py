"""replace_legacy_bookings_table

Revision ID: b7c2e8f9a3d1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-14 15:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = 'b7c2e8f9a3d1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def _model_columns_present(inspector, table: str, required: set[str]) -> bool:
    return required.issubset({c["name"] for c in inspector.get_columns(table)})


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "bookings" not in table_names:
        return

    model_required = {
        "appointment_date",
        "appointment_time",
        "status",
        "booking_type",
        "recommendation_id",
        "linked_assessment_id",
        "provider_name",
        "patient_name_snapshot",
    }

    if _model_columns_present(inspector, "bookings", model_required):
        return

    if "bookings_legacy_v1" not in table_names:
        # Drop indexes on legacy table whose names we want to reuse on the new table.
        existing_legacy_indexes = {idx["name"] for idx in inspector.get_indexes("bookings")}
        for idx_name in (
            "ix_bookings_user_id",
            "ix_bookings_doctor_id",
            "ix_bookings_hospital_id",
            "ix_bookings_recommendation_id",
            "ix_bookings_linked_assessment_id",
            "ix_bookings_client_request_id",
            "ix_bookings_provider_external_id",
            "ix_bookings_status_created_at",
            "ix_bookings_booking_type",
            "ix_bookings_created_at",
        ):
            if idx_name in existing_legacy_indexes:
                op.drop_index(idx_name, table_name="bookings")
        op.rename_table("bookings", "bookings_legacy_v1")

    booking_status_enum = postgresql.ENUM(
        "PENDING", "CONFIRMED", "COMPLETED", "CANCELLED",
        name="booking_status",
        create_type=False,
    )
    booking_type_enum = postgresql.ENUM(
        "ONLINE", "IN_PERSON",
        name="booking_type",
        create_type=False,
    )
    booking_status_enum.create(bind, checkfirst=True)
    booking_type_enum.create(bind, checkfirst=True)

    referenced_tables = set(inspect(bind).get_table_names())

    columns = [
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("doctor_id", sa.String(length=36), nullable=True),
        sa.Column("hospital_id", sa.String(length=36), nullable=True),
        sa.Column("recommendation_id", sa.String(length=36), nullable=True),
        sa.Column("linked_assessment_id", sa.String(length=36), nullable=True),
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
        sa.Column("provider_name", sa.String(length=255), nullable=True),
        sa.Column("provider_external_id", sa.String(length=120), nullable=True),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("location_address", sa.Text(), nullable=True),
        sa.Column("patient_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("patient_phone_snapshot", sa.String(length=30), nullable=True),
        sa.Column("patient_sex_snapshot", sa.String(length=30), nullable=True),
        sa.Column("appointment_date", sa.Date(), nullable=False),
        sa.Column("appointment_time", sa.Time(), nullable=False),
        sa.Column("status", booking_status_enum, nullable=False),
        sa.Column("booking_type", booking_type_enum, nullable=False),
        sa.Column("symptoms_summary", sa.Text(), nullable=True),
        sa.Column("prescription_ids", sa.JSON(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="booking_rating_check",
        ),
    ]

    fk_specs = [
        ("user_id", "users", "id", "CASCADE"),
        ("doctor_id", "doctors", "id", "SET NULL"),
        ("hospital_id", "hospitals", "id", "SET NULL"),
        ("recommendation_id", "doctor_recommendations", "id", "SET NULL"),
        ("linked_assessment_id", "assessment_documents", "id", "SET NULL"),
    ]
    bookings_id_type = "VARCHAR"  # we're creating new bookings columns as String(36)
    for col, ref_table, ref_col, ondelete in fk_specs:
        if ref_table not in referenced_tables:
            continue
        ref_cols = {c["name"]: str(c["type"]).upper() for c in inspect(bind).get_columns(ref_table)}
        ref_type = ref_cols.get(ref_col, "")
        # Skip FK if referenced column's type isn't compatible with VARCHAR(36).
        if "VARCHAR" not in ref_type and "CHAR" not in ref_type and "TEXT" not in ref_type:
            continue
        columns.append(sa.ForeignKeyConstraint([col], [f"{ref_table}.{ref_col}"], ondelete=ondelete))

    op.create_table("bookings", *columns)
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"], unique=False)
    op.create_index("ix_bookings_doctor_id", "bookings", ["doctor_id"], unique=False)
    op.create_index("ix_bookings_hospital_id", "bookings", ["hospital_id"], unique=False)
    op.create_index("ix_bookings_recommendation_id", "bookings", ["recommendation_id"], unique=False)
    op.create_index("ix_bookings_linked_assessment_id", "bookings", ["linked_assessment_id"], unique=False)
    op.create_index("ix_bookings_client_request_id", "bookings", ["client_request_id"], unique=True)
    op.create_index("ix_bookings_provider_external_id", "bookings", ["provider_external_id"], unique=False)
    op.create_index("ix_bookings_status_created_at", "bookings", ["status", "created_at"], unique=False)
    op.create_index("ix_bookings_booking_type", "bookings", ["booking_type"], unique=False)
    op.create_index("ix_bookings_created_at", "bookings", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "bookings" in table_names:
        for idx_name in (
            "ix_bookings_user_id",
            "ix_bookings_doctor_id",
            "ix_bookings_hospital_id",
            "ix_bookings_recommendation_id",
            "ix_bookings_linked_assessment_id",
            "ix_bookings_client_request_id",
            "ix_bookings_provider_external_id",
            "ix_bookings_status_created_at",
            "ix_bookings_booking_type",
            "ix_bookings_created_at",
        ):
            try:
                op.drop_index(idx_name, table_name="bookings")
            except Exception:
                pass
        op.drop_table("bookings")

    if "bookings_legacy_v1" in table_names:
        op.rename_table("bookings_legacy_v1", "bookings")

    booking_status_enum = sa.Enum(name="booking_status")
    booking_type_enum = sa.Enum(name="booking_type")
    booking_status_enum.drop(bind, checkfirst=True)
    booking_type_enum.drop(bind, checkfirst=True)
