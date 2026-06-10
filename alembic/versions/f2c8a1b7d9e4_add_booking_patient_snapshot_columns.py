"""add_booking_patient_snapshot_columns

Revision ID: f2c8a1b7d9e4
Revises: e1f7c4d9a2b6
Create Date: 2026-04-22 18:40:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2c8a1b7d9e4"
down_revision = "e1f7c4d9a2b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    booking_columns = {column["name"] for column in inspector.get_columns("bookings")}

    with op.batch_alter_table("bookings") as batch_op:
        if "patient_name_snapshot" not in booking_columns:
            batch_op.add_column(sa.Column("patient_name_snapshot", sa.String(length=255), nullable=True))
        if "patient_phone_snapshot" not in booking_columns:
            batch_op.add_column(sa.Column("patient_phone_snapshot", sa.String(length=30), nullable=True))
        if "patient_sex_snapshot" not in booking_columns:
            batch_op.add_column(sa.Column("patient_sex_snapshot", sa.String(length=30), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    booking_columns = {column["name"] for column in inspector.get_columns("bookings")}

    with op.batch_alter_table("bookings") as batch_op:
        if "patient_sex_snapshot" in booking_columns:
            batch_op.drop_column("patient_sex_snapshot")
        if "patient_phone_snapshot" in booking_columns:
            batch_op.drop_column("patient_phone_snapshot")
        if "patient_name_snapshot" in booking_columns:
            batch_op.drop_column("patient_name_snapshot")
