"""V2 domain schema: 15 tables (blueprint §5.1–§5.15)

Revision ID: 0003_v2_domain
Revises: 0002_jobs
Create Date: 2026-09-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_v2_domain"
down_revision: str | None = "0002_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filepath", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("extension", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("codec", sa.String(), nullable=True),
        sa.Column("container", sa.String(), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("bit_depth", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("channel_layout", sa.String(), nullable=True),
        sa.Column("scan_state", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filepath"),
    )
    op.create_index(op.f("ix_files_filepath"), "files", ["filepath"], unique=True)
    op.create_index(op.f("ix_files_sha256"), "files", ["sha256"], unique=False)
    op.create_index(op.f("ix_files_scan_state"), "files", ["scan_state"], unique=False)

    op.create_table(
        "artists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("musicbrainz_artist_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_name", sa.String(), nullable=True),
        sa.Column("disambiguation", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("musicbrainz_artist_id"),
    )
    op.create_index(op.f("ix_artists_name"), "artists", ["name"], unique=False)

    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("musicbrainz_recording_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("artist_credit", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("isrc", sa.String(), nullable=True),
        sa.Column("disambiguation", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("musicbrainz_recording_id"),
    )
    op.create_index(op.f("ix_recordings_title"), "recordings", ["title"], unique=False)

    op.create_table(
        "release_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("musicbrainz_release_group_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("primary_type", sa.String(), nullable=True),
        sa.Column("secondary_types_json", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("musicbrainz_release_group_id"),
    )
    op.create_index(op.f("ix_release_groups_title"), "release_groups", ["title"], unique=False)

    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_group_id", sa.Integer(), nullable=False),
        sa.Column("musicbrainz_release_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("barcode", sa.String(), nullable=True),
        sa.Column("media_json", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["release_group_id"], ["release_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("musicbrainz_release_id"),
    )
    op.create_index(op.f("ix_releases_release_group_id"), "releases", ["release_group_id"], unique=False)

    op.create_table(
        "release_tracks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("disc_number", sa.Integer(), nullable=False),
        sa.Column("track_number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("length_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"]),
        sa.PrimaryKeyConstraint("id"),
        UniqueConstraint(
            "release_id",
            "disc_number",
            "track_number",
            "recording_id",
            name="uq_release_track_position",
        ),
    )
    op.create_index(op.f("ix_release_tracks_release_id"), "release_tracks", ["release_id"], unique=False)
    op.create_index(op.f("ix_release_tracks_recording_id"), "release_tracks", ["recording_id"], unique=False)

    op.create_table(
        "file_recordings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(10, 6), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("matched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_index(op.f("ix_file_recordings_file_id"), "file_recordings", ["file_id"], unique=True)
    op.create_index(op.f("ix_file_recordings_recording_id"), "file_recordings", ["recording_id"], unique=False)

    op.create_table(
        "file_releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("release_track_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(10, 6), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("matched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"]),
        sa.ForeignKeyConstraint(["release_track_id"], ["release_tracks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_index(op.f("ix_file_releases_file_id"), "file_releases", ["file_id"], unique=True)
    op.create_index(op.f("ix_file_releases_release_id"), "file_releases", ["release_id"], unique=False)
    op.create_index(op.f("ix_file_releases_release_track_id"), "file_releases", ["release_track_id"], unique=False)

    op.create_table(
        "fingerprints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("fingerprint_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_index(op.f("ix_fingerprints_file_id"), "fingerprints", ["file_id"], unique=True)

    op.create_table(
        "artworks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("is_embedded", sa.Boolean(), nullable=False),
        sa.Column("quality_score", sa.Numeric(10, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artworks_release_id"), "artworks", ["release_id"], unique=False)
    op.create_index(op.f("ix_artworks_file_id"), "artworks", ["file_id"], unique=False)

    op.create_table(
        "audio_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("bpm", sa.Numeric(10, 4), nullable=True),
        sa.Column("musical_key", sa.String(), nullable=True),
        sa.Column("integrated_lufs", sa.Numeric(10, 4), nullable=True),
        sa.Column("true_peak_db", sa.Numeric(10, 4), nullable=True),
        sa.Column("replaygain_track_db", sa.Numeric(10, 4), nullable=True),
        sa.Column("replaygain_album_db", sa.Numeric(10, 4), nullable=True),
        sa.Column("dynamic_range", sa.Numeric(10, 4), nullable=True),
        sa.Column("spectral_centroid", sa.Numeric(10, 4), nullable=True),
        sa.Column("frequency_ceiling_hz", sa.Numeric(10, 1), nullable=True),
        sa.Column("analysis_version", sa.String(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_index(op.f("ix_audio_features_file_id"), "audio_features", ["file_id"], unique=True)

    op.create_table(
        "metadata_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=True),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(10, 6), nullable=False),
        sa.Column("confidence_level", sa.String(), nullable=False),
        sa.Column("reasoning_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metadata_candidates_file_id"), "metadata_candidates", ["file_id"], unique=False)
    op.create_index(op.f("ix_metadata_candidates_status"), "metadata_candidates", ["status"], unique=False)

    op.create_table(
        "metadata_provenance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("value_text", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("confidence", sa.Numeric(10, 6), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["metadata_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metadata_provenance_file_id"), "metadata_provenance", ["file_id"], unique=False)

    op.create_table(
        "change_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_change_sets_status"), "change_sets", ["status"], unique=False)

    op.create_table(
        "changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_set_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("old_value_json", sa.Text(), nullable=True),
        sa.Column("new_value_json", sa.Text(), nullable=True),
        sa.Column("old_path", sa.String(), nullable=True),
        sa.Column("new_path", sa.String(), nullable=True),
        sa.Column("backup_path", sa.String(), nullable=True),
        sa.Column("verification_status", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_changes_change_set_id"), "changes", ["change_set_id"], unique=False)
    op.create_index(op.f("ix_changes_file_id"), "changes", ["file_id"], unique=False)

    # files table now exists — attach the deferred job_items.file_id FK (TV2-006).
    with op.batch_alter_table("job_items") as batch_op:
        batch_op.create_foreign_key("fk_job_items_file_id", "files", ["file_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("job_items") as batch_op:
        batch_op.drop_constraint("fk_job_items_file_id", type_="foreignkey")

    op.drop_index(op.f("ix_changes_file_id"), table_name="changes")
    op.drop_index(op.f("ix_changes_change_set_id"), table_name="changes")
    op.drop_table("changes")
    op.drop_index(op.f("ix_change_sets_status"), table_name="change_sets")
    op.drop_table("change_sets")
    op.drop_index(op.f("ix_metadata_provenance_file_id"), table_name="metadata_provenance")
    op.drop_table("metadata_provenance")
    op.drop_index(op.f("ix_metadata_candidates_status"), table_name="metadata_candidates")
    op.drop_index(op.f("ix_metadata_candidates_file_id"), table_name="metadata_candidates")
    op.drop_table("metadata_candidates")
    op.drop_index(op.f("ix_audio_features_file_id"), table_name="audio_features")
    op.drop_table("audio_features")
    op.drop_index(op.f("ix_artworks_file_id"), table_name="artworks")
    op.drop_index(op.f("ix_artworks_release_id"), table_name="artworks")
    op.drop_table("artworks")
    op.drop_index(op.f("ix_fingerprints_file_id"), table_name="fingerprints")
    op.drop_table("fingerprints")
    op.drop_index(op.f("ix_file_releases_release_track_id"), table_name="file_releases")
    op.drop_index(op.f("ix_file_releases_release_id"), table_name="file_releases")
    op.drop_index(op.f("ix_file_releases_file_id"), table_name="file_releases")
    op.drop_table("file_releases")
    op.drop_index(op.f("ix_file_recordings_recording_id"), table_name="file_recordings")
    op.drop_index(op.f("ix_file_recordings_file_id"), table_name="file_recordings")
    op.drop_table("file_recordings")
    op.drop_index(op.f("ix_release_tracks_recording_id"), table_name="release_tracks")
    op.drop_index(op.f("ix_release_tracks_release_id"), table_name="release_tracks")
    op.drop_table("release_tracks")
    op.drop_index(op.f("ix_releases_release_group_id"), table_name="releases")
    op.drop_table("releases")
    op.drop_index(op.f("ix_release_groups_title"), table_name="release_groups")
    op.drop_table("release_groups")
    op.drop_index(op.f("ix_recordings_title"), table_name="recordings")
    op.drop_table("recordings")
    op.drop_index(op.f("ix_artists_name"), table_name="artists")
    op.drop_table("artists")
    op.drop_index(op.f("ix_files_scan_state"), table_name="files")
    op.drop_index(op.f("ix_files_sha256"), table_name="files")
    op.drop_index(op.f("ix_files_filepath"), table_name="files")
    op.drop_table("files")