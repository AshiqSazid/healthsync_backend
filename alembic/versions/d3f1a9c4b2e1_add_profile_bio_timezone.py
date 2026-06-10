"""add_profile_bio_timezone

Revision ID: d3f1a9c4b2e1
Revises: b8d1c4f2e7a9
Create Date: 2026-04-13 22:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d3f1a9c4b2e1"
down_revision = "b8d1c4f2e7a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    profile_columns = {column["name"] for column in inspector.get_columns("profiles")}

    with op.batch_alter_table("profiles") as batch_op:
        if "bio" not in profile_columns:
            batch_op.add_column(sa.Column("bio", sa.String(length=500), nullable=True))
        if "timezone" not in profile_columns:
            batch_op.add_column(sa.Column("timezone", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    profile_columns = {column["name"] for column in inspector.get_columns("profiles")}

    with op.batch_alter_table("profiles") as batch_op:
        if "timezone" in profile_columns:
            batch_op.drop_column("timezone")
        if "bio" in profile_columns:
            batch_op.drop_column("bio")
