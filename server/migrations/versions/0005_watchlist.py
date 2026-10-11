"""watchlist_item: the owner's own selection across asset classes

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_item",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("watchlist_item")
