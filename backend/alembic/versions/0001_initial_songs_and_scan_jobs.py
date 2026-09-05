"""Initial songs and scan_jobs tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "songs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("filepath", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sha256", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("artist", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("album", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("album_artist", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("composer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("genre", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("track_number", sa.Integer(), nullable=True),
        sa.Column("disc_number", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("codec", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("musical_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("lyrics", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("has_cover", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_songs_album"), "songs", ["album"], unique=False)
    op.create_index(op.f("ix_songs_artist"), "songs", ["artist"], unique=False)
    op.create_index(op.f("ix_songs_filename"), "songs", ["filename"], unique=False)
    op.create_index(op.f("ix_songs_filepath"), "songs", ["filepath"], unique=True)
    op.create_index(op.f("ix_songs_genre"), "songs", ["genre"], unique=False)
    op.create_index(op.f("ix_songs_sha256"), "songs", ["sha256"], unique=False)
    op.create_index(op.f("ix_songs_title"), "songs", ["title"], unique=False)

    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("directory_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending"
        ),
        sa.Column("scanned_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scan_jobs_status"), "scan_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scan_jobs_status"), table_name="scan_jobs")
    op.drop_table("scan_jobs")
    op.drop_index(op.f("ix_songs_title"), table_name="songs")
    op.drop_index(op.f("ix_songs_sha256"), table_name="songs")
    op.drop_index(op.f("ix_songs_genre"), table_name="songs")
    op.drop_index(op.f("ix_songs_filepath"), table_name="songs")
    op.drop_index(op.f("ix_songs_filename"), table_name="songs")
    op.drop_index(op.f("ix_songs_artist"), table_name="songs")
    op.drop_index(op.f("ix_songs_album"), table_name="songs")
    op.drop_table("songs")
