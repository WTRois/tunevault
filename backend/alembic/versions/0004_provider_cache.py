"""provider_cache table (blueprint §26)

Revision ID: 0004_provider_cache
Revises: 0003_v2_domain
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_provider_cache"
down_revision: str | None = "0003_v2_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cache_key", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_index(op.f("ix_provider_cache_cache_key"), "provider_cache", ["cache_key"], unique=True)
    op.create_index(op.f("ix_provider_cache_provider"), "provider_cache", ["provider"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_provider_cache_provider"), table_name="provider_cache")
    op.drop_index(op.f("ix_provider_cache_cache_key"), table_name="provider_cache")
    op.drop_table("provider_cache")