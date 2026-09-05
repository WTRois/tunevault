import csv
import io
import json

from fastapi import APIRouter, Depends, Query, Response
from openpyxl import Workbook
from sqlmodel import Session

from backend.database.session import get_session
from backend.repositories.song_repository import SongRepository
from backend.schemas.song import SongRead

router = APIRouter(prefix="/export", tags=["Export"])

EXPORT_COLUMNS = [
    "id",
    "filename",
    "filepath",
    "sha256",
    "title",
    "artist",
    "album",
    "album_artist",
    "composer",
    "genre",
    "year",
    "track_number",
    "disc_number",
    "duration",
    "bitrate",
    "codec",
    "sample_rate",
    "channels",
    "file_size",
    "bpm",
    "musical_key",
    "lyrics",
    "has_cover",
]


def _get_filtered_songs_data(
    session: Session,
    search: str | None,
    artist: str | None,
    album: str | None,
    genre: str | None,
) -> list[dict]:
    """Fetch matching songs up to max limit of 10,000 for export."""
    songs, _ = SongRepository.list_songs(
        session=session,
        page=1,
        limit=10000,
        sort_by="id",
        order="asc",
        search=search,
        artist=artist,
        album=album,
        genre=genre,
    )
    return [SongRead.model_validate(song).model_dump(mode="json") for song in songs]


@router.get("/json")
def export_metadata_json(
    search: str | None = Query(default=None),
    artist: str | None = Query(default=None),
    album: str | None = Query(default=None),
    genre: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Export catalog metadata in JSON format."""
    songs_data = _get_filtered_songs_data(session, search, artist, album, genre)
    json_bytes = json.dumps(songs_data, indent=2, default=str).encode("utf-8")

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="tunevault_export.json"'},
    )


@router.get("/csv")
def export_metadata_csv(
    search: str | None = Query(default=None),
    artist: str | None = Query(default=None),
    album: str | None = Query(default=None),
    genre: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Export catalog metadata in CSV format."""
    songs_data = _get_filtered_songs_data(session, search, artist, album, genre)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()

    for song in songs_data:
        filtered_row = {col: song.get(col, "") for col in EXPORT_COLUMNS}
        writer.writerow(filtered_row)

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tunevault_export.csv"'},
    )


@router.get("/xlsx")
def export_metadata_xlsx(
    search: str | None = Query(default=None),
    artist: str | None = Query(default=None),
    album: str | None = Query(default=None),
    genre: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Export catalog metadata in Microsoft Excel (.xlsx) format using openpyxl."""
    songs_data = _get_filtered_songs_data(session, search, artist, album, genre)

    wb = Workbook()
    ws = wb.active
    ws.title = "TuneVault Metadata"

    # Write Header
    ws.append(EXPORT_COLUMNS)

    # Write Rows
    for song in songs_data:
        row = [song.get(col) for col in EXPORT_COLUMNS]
        ws.append(row)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tunevault_export.xlsx"'},
    )
