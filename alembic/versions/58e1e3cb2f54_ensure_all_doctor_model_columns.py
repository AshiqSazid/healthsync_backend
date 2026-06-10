"""ensure_all_doctor_model_columns

Revision ID: 58e1e3cb2f54
Revises: 5e57b08ca681
Create Date: 2026-05-14 11:06:22.793345

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '58e1e3cb2f54'
down_revision = '5e57b08ca681'
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

    column_definitions = {
        "user_id": sa.Column("user_id", sa.String(length=36), nullable=True),
        "specialization": sa.Column("specialization", sa.JSON(), nullable=True),
        "sub_specializations": sa.Column("sub_specializations", sa.JSON(), nullable=True),
        "license_number": sa.Column("license_number", sa.String(length=120), nullable=True),
        "experience_years": sa.Column("experience_years", sa.Integer(), nullable=True),
        "consultation_fee": sa.Column("consultation_fee", sa.Numeric(10, 2), nullable=True),
        "hospital_id": sa.Column("hospital_id", sa.String(length=36), nullable=True),
        "average_rating": sa.Column("average_rating", sa.Float(), nullable=True),
        "available_slots": sa.Column("available_slots", sa.JSON(), nullable=True),
        "languages_spoken": sa.Column("languages_spoken", sa.JSON(), nullable=True),
        "conditions_treated": sa.Column("conditions_treated", sa.JSON(), nullable=True),
        "education": sa.Column("education", sa.JSON(), nullable=True),
        "certifications": sa.Column("certifications", sa.JSON(), nullable=True),
        "photo_url": sa.Column("photo_url", sa.String(length=1000), nullable=True),
        "photo_filename": sa.Column("photo_filename", sa.String(length=255), nullable=True),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    }

    for column_name, column in column_definitions.items():
        if column_name not in doctor_columns:
            op.add_column("doctors", column)
            doctor_columns.add(column_name)

    has_user_fk = any(
        fk.get("referred_table") == "users" and fk.get("constrained_columns") == ["user_id"]
        for fk in doctor_foreign_keys
    )
    has_hospital_fk = any(
        fk.get("referred_table") == "hospitals" and fk.get("constrained_columns") == ["hospital_id"]
        for fk in doctor_foreign_keys
    )

    if "user_id" in doctor_columns and not has_user_fk:
        op.create_foreign_key(
            "fk_doctors_user_id_users",
            "doctors",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if "hospital_id" in doctor_columns and "hospitals" in table_names and not has_hospital_fk:
        op.create_foreign_key(
            "fk_doctors_hospital_id_hospitals",
            "doctors",
            "hospitals",
            ["hospital_id"],
            ["id"],
            ondelete="SET NULL",
        )

    index_definitions = {
        "ix_doctors_created_at": (["created_at"], False),
        "ix_doctors_hospital_id": (["hospital_id"], False),
        "ix_doctors_license_number": (["license_number"], True),
        "ix_doctors_user_id": (["user_id"], True),
    }
    for index_name, (columns, unique) in index_definitions.items():
        if index_name not in doctor_indexes and all(column in doctor_columns for column in columns):
            op.create_index(index_name, "doctors", columns, unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "doctors" not in table_names:
        return

    doctor_columns = {column["name"] for column in inspector.get_columns("doctors")}
    doctor_indexes = {index["name"] for index in inspector.get_indexes("doctors")}
    doctor_foreign_keys = {fk.get("name") for fk in inspector.get_foreign_keys("doctors") if fk.get("name")}

    for index_name in (
        "ix_doctors_user_id",
        "ix_doctors_license_number",
        "ix_doctors_hospital_id",
        "ix_doctors_created_at",
    ):
        if index_name in doctor_indexes:
            op.drop_index(index_name, table_name="doctors")

    for constraint_name in ("fk_doctors_hospital_id_hospitals", "fk_doctors_user_id_users"):
        if constraint_name in doctor_foreign_keys:
            op.drop_constraint(constraint_name, "doctors", type_="foreignkey")

    for column_name in (
        "updated_at",
        "created_at",
        "photo_filename",
        "photo_url",
        "certifications",
        "education",
        "conditions_treated",
        "languages_spoken",
        "available_slots",
        "average_rating",
        "hospital_id",
        "consultation_fee",
        "experience_years",
        "license_number",
        "sub_specializations",
        "specialization",
        "user_id",
    ):
        if column_name in doctor_columns:
            op.drop_column("doctors", column_name)
