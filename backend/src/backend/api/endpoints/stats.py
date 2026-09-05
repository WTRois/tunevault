from fastapi import APIRouter, Depends
from sqlmodel import Session, col, func, select

from backend.database.session import get_session
from backend.models import File, FileRecording, MetadataProvenance, Recording
from backend.schemas.stats import StatsOverviewResponse

router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("", response_model=StatsOverviewResponse)
def get_catalog_statistics(session: Session = Depends(get_session)):
    """Retrieve aggregated stats for dashboard overview (V2 schema, §40 Option B)."""
    total_songs = session.exec(select(func.count(File.id))).one() or 0

    total_artists = (
        session.exec(
            select(func.count(func.distinct(Recording.artist_credit)))
            .join(FileRecording, FileRecording.recording_id == Recording.id)
            .where(col(Recording.artist_credit).is_not(None))
        ).one()
        or 0
    )

    def _distinct_provenance(field: str) -> int:
        return (
            session.exec(
                select(func.count(func.distinct(MetadataProvenance.value_text))).where(
                    MetadataProvenance.field_name == field,
                    col(MetadataProvenance.value_text).is_not(None),
                )
            ).one()
            or 0
        )

    total_albums = _distinct_provenance("album")
    total_genres = _distinct_provenance("genre")

    total_duration_ms = session.exec(select(func.sum(File.duration_ms))).one() or 0
    total_file_size = session.exec(select(func.sum(File.file_size))).one() or 0

    # Codecs breakdown
    codec_counts = session.exec(select(File.codec, func.count(File.id)).group_by(File.codec)).all()

    codecs_dict = {(codec if codec else "unknown"): count for codec, count in codec_counts}

    return StatsOverviewResponse(
        total_songs=total_songs,
        total_artists=total_artists,
        total_albums=total_albums,
        total_genres=total_genres,
        total_duration=float(total_duration_ms) / 1000.0,
        total_file_size=int(total_file_size),
        codecs=codecs_dict,
    )