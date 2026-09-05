import math
import os
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session

from backend.core.config import settings
from backend.core.paths import (
    PathNotFoundError,
    PathOutsideRootsError,
    validate_read,
    validate_write,
)
from backend.database.session import get_session
from backend.repositories.song_repository import SongRepository
from backend.schemas.song import (
    LyricsEmbedRequest,
    LyricsFetchResponse,
    MetadataMatchEmbedRequest,
    MetadataMatchSearchResponse,
    PaginatedSongsResponse,
    SongRead,
    SongUpdate,
)
from backend.services import lrclib, youtube_metadata
from backend.services.tag_writer import embed_cover_art, remove_cover_art, write_text_metadata

router = APIRouter(prefix="/songs", tags=["Songs"])


def _song_file(song, *, write: bool):
    """Gate song.filepath through the path sandbox (§27.4) before touching the FS."""
    try:
        return validate_write(song.filepath) if write else validate_read(song.filepath)
    except PathNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Physical audio file not found on disk at '{song.filepath}'.",
        ) from err
    except PathOutsideRootsError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from err

# Aesthetic SVG Placeholder for missing Cover Art
DEFAULT_COVER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
  <rect width="300" height="300" fill="#1d232a"/>
  <circle cx="150" cy="150" r="80" fill="#2a323c" stroke="#374151" stroke-width="4"/>
  <path d="M140 120v40c-2.2-1.3-4.9-2-8-2-8.8 0-16 7.2-16 16s7.2 16 16 16 16-7.2 16-16v-34h20v-20h-28z" fill="#7480ff"/>
</svg>"""


@router.get("", response_model=PaginatedSongsResponse)
def list_songs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="id"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    search: str | None = Query(default=None),
    artist: str | None = Query(default=None),
    album: str | None = Query(default=None),
    genre: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Retrieve list of songs with search, filtering, sorting, and pagination."""
    allowed_sort_fields = {
        "id",
        "title",
        "artist",
        "album",
        "genre",
        "year",
        "duration",
        "bpm",
        "created_at",
    }
    if sort_by not in allowed_sort_fields:
        sort_by = "id"

    songs, total = SongRepository.list_songs(
        session=session,
        page=page,
        limit=limit,
        sort_by=sort_by,
        order=order,
        search=search,
        artist=artist,
        album=album,
        genre=genre,
    )

    pages = math.ceil(total / limit) if limit > 0 else 1

    return PaginatedSongsResponse(
        items=songs,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.get("/{song_id}", response_model=SongRead)
def get_song(song_id: int, session: Session = Depends(get_session)):
    """Retrieve detailed metadata for a single song."""
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )
    return song


@router.put("/{song_id}/metadata", response_model=SongRead)
def update_song_metadata(
    song_id: int,
    payload: SongUpdate,
    session: Session = Depends(get_session),
):
    """Update song metadata text tags on physical audio file and index."""
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )

    _song_file(song, write=True)

    update_dict = payload.model_dump(exclude_unset=True)

    try:
        # Write tags to physical audio file
        new_sha256 = write_text_metadata(song.filepath, update_dict)
        update_dict["sha256"] = new_sha256
        update_dict["filepath"] = song.filepath

        # Update database record
        updated_song, _ = SongRepository.upsert_song(session, update_dict)
        return updated_song

    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write metadata tags to audio file: {err}",
        ) from err


@router.post("/{song_id}/lyrics/fetch", response_model=LyricsFetchResponse)
def fetch_song_lyrics(song_id: int, session: Session = Depends(get_session)):
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if not song.title or not song.artist or not song.duration:
        raise HTTPException(status_code=422, detail="Title, artist, and duration are required")
    try:
        exact = lrclib.lookup_exact(song)
        if exact:
            return LyricsFetchResponse(status="exact_match", lyrics=exact)
        return LyricsFetchResponse(
            status="selection_required", candidates=lrclib.search_candidates(song)
        )
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err


@router.put("/{song_id}/lyrics", response_model=SongRead)
def embed_song_lyrics(
    song_id: int,
    payload: LyricsEmbedRequest,
    session: Session = Depends(get_session),
):
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song or physical audio file not found")
    _song_file(song, write=True)
    try:
        new_sha256 = write_text_metadata(song.filepath, {"lyrics": payload.lyrics})
        updated_song, _ = SongRepository.upsert_song(
            session, {"filepath": song.filepath, "lyrics": payload.lyrics, "sha256": new_sha256}
        )
        return updated_song
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to embed lyrics: {err}") from err


@router.post("/{song_id}/metadata-match/search", response_model=MetadataMatchSearchResponse)
def search_song_metadata(song_id: int, session: Session = Depends(get_session)):
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if not song.title and not song.artist:
        raise HTTPException(status_code=422, detail="Title or artist is required")
    try:
        query, candidates = youtube_metadata.search_candidates(song)
        return MetadataMatchSearchResponse(query=query, candidates=candidates)
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err


@router.put("/{song_id}/metadata-match", response_model=SongRead)
def embed_matched_metadata(
    song_id: int,
    payload: MetadataMatchEmbedRequest,
    session: Session = Depends(get_session),
):
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song or physical audio file not found")
    _song_file(song, write=True)
    try:
        update_data: dict[str, Any] = dict(payload.metadata)
        new_sha256 = write_text_metadata(song.filepath, update_data)
        update_data.update({"filepath": song.filepath, "sha256": new_sha256})
        updated_song, _ = SongRepository.upsert_song(session, update_data)
        return updated_song
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to embed metadata: {err}") from err


@router.post("/{song_id}/cover")
async def upload_song_cover(
    song_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Upload and embed new Cover Art image into physical audio file."""
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )

    _song_file(song, write=True)

    try:
        image_bytes = await file.read()
        new_sha256, _ = embed_cover_art(song.filepath, image_bytes)

        # Update song record in database
        update_data = {
            "filepath": song.filepath,
            "sha256": new_sha256,
            "has_cover": True,
        }
        SongRepository.upsert_song(session, update_data)

        return {
            "message": "Cover art embedded successfully.",
            "song_id": song_id,
            "sha256": new_sha256,
            "has_cover": True,
        }

    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to embed cover art: {err}",
        ) from err


@router.delete("/{song_id}/cover")
def delete_song_cover(song_id: int, session: Session = Depends(get_session)):
    """Remove embedded Cover Art from physical audio file."""
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )

    _song_file(song, write=True)

    try:
        new_sha256 = remove_cover_art(song.filepath)

        # Delete local cache if present
        cache_path = os.path.join(settings.resolved_covers_dir, f"{song.sha256}.jpg")
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except Exception:  # noqa: BLE001, S110
                pass

        update_data = {
            "filepath": song.filepath,
            "sha256": new_sha256,
            "has_cover": False,
        }
        SongRepository.upsert_song(session, update_data)

        return {
            "message": "Cover art removed from audio file successfully.",
            "song_id": song_id,
            "sha256": new_sha256,
            "has_cover": False,
        }

    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove cover art: {err}",
        ) from err


@router.delete("/{song_id}", status_code=status.HTTP_200_OK)
def delete_song(song_id: int, session: Session = Depends(get_session)):
    """Delete a song record from index (file on disk is preserved)."""
    deleted = SongRepository.delete_song(session, song_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )
    return {"message": f"Song {song_id} deleted successfully."}


@router.get("/{song_id}/cover")
def get_song_cover(song_id: int, session: Session = Depends(get_session)):
    """Serve embedded Cover Art image for a song or return SVG placeholder."""
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )

    headers = {"Cache-Control": "public, max-age=86400"}

    cover_file = os.path.join(settings.resolved_covers_dir, f"{song.sha256}.jpg")
    if os.path.exists(cover_file):
        return FileResponse(cover_file, media_type="image/jpeg", headers=headers)

    return Response(content=DEFAULT_COVER_SVG, media_type="image/svg+xml", headers=headers)


@router.get("/{song_id}/stream")
def stream_song_audio(
    song_id: int,
    session: Session = Depends(get_session),
    range_header: str | None = Header(default=None, alias="Range"),
):
    """Stream an audio file with single-range HTTP 206 support for seeking."""
    song = SongRepository.get_by_id(session, song_id)
    if not song:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Song with ID {song_id} not found.",
        )

    _song_file(song, write=False)

    import mimetypes

    mime_type, _ = mimetypes.guess_type(song.filepath)
    mime_type = mime_type or "audio/mpeg"
    file_size = os.path.getsize(song.filepath)
    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }

    if not range_header:
        return FileResponse(song.filepath, media_type=mime_type, headers=common_headers)

    if not range_header.startswith("bytes=") or "," in range_header:
        raise HTTPException(
            status_code=416,
            detail="Only a single bytes range is supported.",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    range_value = range_header.removeprefix("bytes=").strip()
    start_text, separator, end_text = range_value.partition("-")
    if not separator or (not start_text and not end_text):
        raise HTTPException(
            status_code=416,
            detail="Invalid bytes range.",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError as err:
        raise HTTPException(
            status_code=416,
            detail="Invalid bytes range.",
            headers={"Content-Range": f"bytes */{file_size}"},
        ) from err

    if start < 0 or start >= file_size or end < start:
        raise HTTPException(
            status_code=416,
            detail="Requested range is not satisfiable.",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    end = min(end, file_size - 1)
    content_length = end - start + 1

    def iter_file():
        with open(song.filepath, "rb") as audio_file:
            audio_file.seek(start)
            remaining = content_length
            while remaining:
                chunk = audio_file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        **common_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
    }
    return StreamingResponse(
        iter_file(),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=mime_type,
        headers=headers,
    )
