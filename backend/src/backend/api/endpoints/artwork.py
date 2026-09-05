"""Artwork API (blueprint §18 — Artwork section, §11 pipeline, TV2-023).

    GET  /api/releases/{release_id}/artworks
    POST /api/files/{file_id}/artwork/search
    POST /api/files/{file_id}/artwork/apply
"""

import asyncio
import os
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.artwork.quality import artwork_quality_score
from backend.artwork.selector import ArtworkCandidate
from backend.artwork.validator import validate_artwork
from backend.core.paths import PathNotFoundError, PathOutsideRootsError, validate_write
from backend.database.session import get_session
from backend.models import Artwork, File, FileRelease
from backend.providers.coverart import CoverArtProvider, artwork_cache_path
from backend.services.tag_writer import embed_cover_art

router = APIRouter(tags=["Artwork"])


def _release_for_file(session: Session, file_id: int) -> tuple[File, FileRelease]:
    file = session.get(File, file_id)
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"File with ID {file_id} not found.")
    link = session.exec(select(FileRelease).where(FileRelease.file_id == file_id)).first()
    if link is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No identified release for this file — identify it first (TV2-018).",
        )
    return file, link


def _write_cover_file(path: str, data: bytes) -> None:
    """Blocking cover write (called via asyncio.to_thread, §34 async pass)."""
    with open(path, "wb") as f:
        f.write(data)


def _artwork_read(row: Artwork) -> dict:
    return {
        "id": row.id,
        "file_id": row.file_id,
        "release_id": row.release_id,
        "source": row.source,
        "url": row.url,
        "local_path": row.local_path,
        "sha256": row.sha256,
        "mime_type": row.mime_type,
        "width": row.width,
        "height": row.height,
        "type": row.type,
        "is_embedded": row.is_embedded,
        "quality_score": float(row.quality_score) if row.quality_score is not None else None,
    }


def _caa_provider() -> CoverArtProvider:
    """Provider factory; tests may stub this (§26 transport injection)."""
    return CoverArtProvider()


@router.get("/releases/{release_id}/artworks")
def list_release_artworks(release_id: int, session: Session = Depends(get_session)):
    rows = session.exec(
        select(Artwork)
        .where(Artwork.release_id == release_id)
        .order_by(Artwork.quality_score.desc())
    ).all()
    return [_artwork_read(row) for row in rows]


@router.get("/artworks/{artwork_id}/image")
def get_artwork_image(artwork_id: int, session: Session = Depends(get_session)):
    """Serve a cached artwork candidate (thumbnail source for the UI, §11 cache)."""
    row = session.get(Artwork, artwork_id)
    if row is None or not row.local_path or not os.path.exists(row.local_path):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Artwork {artwork_id} not found."
        )
    return FileResponse(row.local_path, media_type=row.mime_type or "image/jpeg")


@router.post("/files/{file_id}/artwork/search")
async def search_artwork(file_id: int, session: Session = Depends(get_session)):
    """§11 pipeline for one file: fetch CAA candidates for its identified
    release, validate, score, cache bytes and persist artworks rows."""
    _file, link = _release_for_file(session, file_id)

    from backend.models import Release

    release_row = session.get(Release, link.release_id)
    if release_row is None or not release_row.musicbrainz_release_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Identified release has no MusicBrainz MBID — cannot query CAA.",
        )

    provider = _caa_provider()
    try:
        images = await provider.release_covers(release_row.musicbrainz_release_id)
    except Exception as err:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Cover Art Archive request failed: {err}"
        ) from err

    candidates: list[ArtworkCandidate] = []
    for image in images:
        try:
            image_bytes = await provider.download(image.url)
        except Exception as err:  # noqa: BLE001, per-image best effort
            logger.warning(f"Failed to download artwork {image.url}: {err}")
            continue
        valid, size = validate_artwork(image_bytes)
        if not valid or size is None:
            continue
        width, height = size
        candidates.append(
            ArtworkCandidate(
                image_bytes=image_bytes,
                source=provider.name,
                url=image.url,
                front=image.front or (image.type or "").lower().startswith("front"),
                mime_type=image.mime_type,
                width=width,
                height=height,
                quality_score=artwork_quality_score(image_bytes, provider.name, image.mime_type),
            )
        )

    saved = []
    for candidate in candidates:
        directory, filename, digest = artwork_cache_path(candidate.image_bytes, candidate.mime_type)
        os.makedirs(directory, exist_ok=True)
        local_path = os.path.join(directory, filename)
        if not os.path.exists(local_path):
            await asyncio.to_thread(
                _write_cover_file, local_path, candidate.image_bytes
            )

        row = Artwork(
            file_id=file_id,
            release_id=link.release_id,
            source=candidate.source,
            url=candidate.url,
            local_path=local_path,
            sha256=digest,
            mime_type=candidate.mime_type,
            width=candidate.width,
            height=candidate.height,
            type="front" if candidate.front else "other",
            quality_score=Decimal(str(candidate.quality_score)),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        saved.append(_artwork_read(row))

    # Sort per §11 policy so the best candidate comes first.
    saved.sort(key=lambda a: (a["type"] == "front", a["quality_score"] or 0), reverse=True)
    return saved


class ArtworkApplyRequest(BaseModel):
    artwork_id: int


@router.post("/files/{file_id}/artwork/apply")
def apply_artwork(
    file_id: int,
    payload: ArtworkApplyRequest | None = None,
    session: Session = Depends(get_session),
):
    """Embed a chosen artwork candidate into the physical file (§11 embed)."""
    if payload is None or payload.artwork_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="artwork_id is required.")

    file, _link = _release_for_file(session, file_id)
    try:
        validate_write(file.filepath)
    except PathNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Physical audio file not found on disk at '{file.filepath}'.",
        ) from err
    except PathOutsideRootsError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from err

    row = session.get(Artwork, payload.artwork_id)
    if row is None or not row.local_path or not os.path.exists(row.local_path):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Artwork {payload.artwork_id} not found."
        )

    with open(row.local_path, "rb") as f:
        image_bytes = f.read()

    try:
        new_sha256, _cache_path = embed_cover_art(file.filepath, image_bytes)
    except Exception as err:
        raise HTTPException(
            status.HTTP_500_INTERNAL_ERROR, detail=f"Failed to embed artwork: {err}"
        ) from err

    row.is_embedded = True
    session.add(row)
    session.commit()

    # Keep the file row in sync with the new on-disk bytes (scan fast-pass
    # would re-extract; do the cheap fields now).
    file.sha256 = new_sha256
    if os.path.exists(file.filepath):
        file.file_size = os.path.getsize(file.filepath)
    session.add(file)
    session.commit()

    return {
        "message": "Artwork embedded.",
        "file_id": file_id,
        "artwork_id": row.id,
        "sha256": new_sha256,
    }