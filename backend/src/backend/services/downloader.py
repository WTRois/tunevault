import os
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlmodel import Session

from backend.core.config import settings
from backend.database.session import engine
from backend.models.job import Job
from backend.repositories.job_repository import JobRepository
from backend.repositories.song_repository import SongRepository
from backend.schemas.downloader import DownloadJobCreate, DownloadPreviewResponse
from backend.services.analyzer import analyze_audio_features
from backend.services.extractor import extract_metadata
from backend.services.tag_writer import embed_cover_art, write_text_metadata

# Download job ids keep the V1 public format ('job_...') backed by jobs-table rows.


def _download_payload(req: DownloadJobCreate) -> dict[str, Any]:
    """Request fields stored in jobs.payload_json for a download job."""
    return {
        "url": req.url,
        "bitrate": req.bitrate,
        "title_override": req.title_override,
        "artist_override": req.artist_override,
        "album_override": req.album_override,
        "auto_import": req.auto_import,
    }


def _job_row_id(job_id: str) -> int | None:
    """Parse the jobs-table row id from a V1-style download job id ('job_123')."""
    try:
        return int(job_id.removeprefix("job_"))
    except ValueError:
        return None


def _load_download_row(session: Session, job_id: str) -> Job | None:
    row_id = _job_row_id(job_id)
    if row_id is None:
        return None
    job = session.get(Job, row_id)
    if job is None or job.job_type != "download":
        return None
    return job


def _download_job_dict(job: Job) -> dict[str, Any]:
    """Map a jobs-table row to the V1 DownloadJobStatusResponse shape (§40 compat)."""
    payload = job.payload_json or {}
    result = job.result_json or {}
    return {
        "job_id": f"job_{job.id}",
        "url": payload.get("url", ""),
        "bitrate": payload.get("bitrate", 192),
        "status": job.status,
        "progress_percent": job.progress,
        "title": result.get("title") or payload.get("title_override"),
        "artist": result.get("artist") or payload.get("artist_override"),
        "file_path": result.get("file_path"),
        "imported_song_id": result.get("imported_song_id"),
        "error_message": job.error_message,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _update_download_job(db_engine, row_id: int, **fields: Any) -> None:
    """Persist a download-job state transition (short session per write)."""
    with Session(db_engine) as session:
        job = session.get(Job, row_id)
        if job is None:
            return
        for key, value in fields.items():
            if key in ("title", "artist", "file_path", "imported_song_id"):
                result = dict(job.result_json or {})
                result[key] = value
                job.result_json = result
            else:
                setattr(job, key, value)
        session.add(job)
        session.commit()


def sanitize_filename(filename: str) -> str:
    """Sanitize string to be safe for filenames across operating systems."""
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    filename = filename.strip(". ")
    return filename or "downloaded_track"


def fetch_url_preview(url: str) -> DownloadPreviewResponse:
    """Extract video metadata and thumbnail from YouTube/YT Music without downloading."""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error(f"yt-dlp preview extraction failed for {url}: {e}")
            raise ValueError(f"Gagal mengambil info dari URL YouTube: {e}") from e

        if not info:
            raise ValueError("URL YouTube tidak mengembalikan metadata.")

        title = info.get("track") or info.get("title") or "Unknown Title"
        artist = (
            info.get("artist") or info.get("uploader") or info.get("channel") or "Unknown Artist"
        )
        album = info.get("album")
        duration = info.get("duration")
        thumbnail_url = info.get("thumbnail")
        source_bitrate = info.get("abr") or info.get("tbr")

        return DownloadPreviewResponse(
            url=url,
            title=title,
            artist=artist,
            album=album,
            duration=float(duration) if duration else None,
            thumbnail_url=thumbnail_url,
            source_bitrate_estimate=int(source_bitrate) if source_bitrate else None,
        )


def create_download_job(req: DownloadJobCreate, db_engine=None) -> str:
    """Create a persistent download job row (blueprint §5.16, job_type='download')."""
    target_engine = db_engine or engine
    with Session(target_engine) as session:
        job = JobRepository.enqueue(session, "download", _download_payload(req))
        return f"job_{job.id}"


def get_download_job(job_id: str, db_engine=None) -> dict[str, Any] | None:
    """Retrieve download job status from the jobs table."""
    target_engine = db_engine or engine
    with Session(target_engine) as session:
        job = _load_download_row(session, job_id)
        if job is None:
            return None
        return _download_job_dict(job)


def delete_download_job(job_id: str, db_engine=None) -> bool:
    """Remove a download job row from the jobs table."""
    target_engine = db_engine or engine
    with Session(target_engine) as session:
        job = _load_download_row(session, job_id)
        if job is None:
            return False
        session.delete(job)
        session.commit()
        return True


def cleanup_temp_downloads(max_age_seconds: int = 86400) -> None:
    """Remove temporary files in storage/downloads older than max_age_seconds (default 24h)."""
    downloads_dir = settings.resolved_downloads_dir
    if not os.path.exists(downloads_dir):
        return

    now = time.time()
    for filename in os.listdir(downloads_dir):
        filepath = os.path.join(downloads_dir, filename)
        if os.path.isfile(filepath):
            try:
                if now - os.path.getmtime(filepath) > max_age_seconds:
                    os.remove(filepath)
                    logger.info(f"Cleaned up old download temp file: {filepath}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Failed to cleanup temp file {filepath}: {e}")


def process_download_job(job_id: str, db_engine=None) -> None:
    """Execute background processing for downloading, converting, tagging, and importing YouTube audio."""
    import yt_dlp

    target_engine = db_engine or engine

    row_id = _job_row_id(job_id)
    if row_id is None:
        logger.error(f"Invalid download job id: {job_id}.")
        return
    with Session(target_engine) as session:
        job = session.get(Job, row_id)
        if job is None or job.job_type != "download":
            logger.error(f"Download job {job_id} not found in job table.")
            return
        payload = dict(job.payload_json or {})

    cleanup_temp_downloads()
    downloads_dir = settings.resolved_downloads_dir
    os.makedirs(downloads_dir, exist_ok=True)

    try:
        # 1. Update status -> DOWNLOADING
        _update_download_job(target_engine, row_id, status="downloading", progress=10.0)

        def _progress_hook(d: dict[str, Any]) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                percent = min(80.0, 10.0 + (downloaded / total) * 70.0)
                _update_download_job(target_engine, row_id, progress=percent)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(downloads_dir, f"{job_id}_raw.%(ext)s"),
            "progress_hooks": [_progress_hook],
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(payload.get("url", ""), download=True)
            if not info:
                raise ValueError("Gagal mengunduh audio dari YouTube.")

        # Determine extracted metadata
        extracted_title = (
            payload.get("title_override")
            or info.get("track")
            or info.get("title")
            or "Unknown Title"
        )
        extracted_artist = (
            payload.get("artist_override")
            or info.get("artist")
            or info.get("uploader")
            or info.get("channel")
            or "Unknown Artist"
        )
        extracted_album = payload.get("album_override") or info.get("album") or "YouTube Music"
        thumbnail_url = info.get("thumbnail")

        _update_download_job(
            target_engine, row_id, title=extracted_title, artist=extracted_artist
        )

        # Find raw downloaded file
        raw_files = [
            os.path.join(downloads_dir, f)
            for f in os.listdir(downloads_dir)
            if f.startswith(f"{job_id}_raw.")
        ]
        if not raw_files:
            raise FileNotFoundError("Berkas audio mentah tidak ditemukan setelah download.")
        raw_filepath = raw_files[0]

        # 2. Update status -> CONVERTING
        _update_download_job(target_engine, row_id, status="converting", progress=82.0)
        converted_mp3_path = os.path.join(downloads_dir, f"{job_id}_converted.mp3")

        target_bitrate = payload.get("bitrate", 192)
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            raw_filepath,
            "-vn",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            f"{target_bitrate}k",
            converted_mp3_path,
        ]

        logger.info(f"Running ffmpeg conversion: {' '.join(ffmpeg_cmd)}")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed with exit code {result.returncode}: {result.stderr.decode('utf-8', errors='ignore')}"
            )

        # Cleanup raw audio file
        if os.path.exists(raw_filepath):
            try:
                os.remove(raw_filepath)
            except Exception as err:  # noqa: BLE001
                logger.debug(f"Failed to remove raw file {raw_filepath}: {err}")

        # 3. Update status -> TAGGING
        _update_download_job(target_engine, row_id, status="tagging", progress=90.0)

        write_text_metadata(
            converted_mp3_path,
            {
                "title": extracted_title,
                "artist": extracted_artist,
                "album": extracted_album,
            },
        )

        # Embed cover art if thumbnail URL is available
        if thumbnail_url:
            try:
                req = urllib.request.Request(thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    img_bytes = resp.read()
                    if img_bytes:
                        embed_cover_art(converted_mp3_path, img_bytes)
            except Exception as img_err:  # noqa: BLE001
                logger.warning(f"Failed to fetch/embed thumbnail cover art: {img_err}")

        # 4. Auto-import to TuneVault /music library if requested
        final_filepath = converted_mp3_path
        imported_song_id = None

        if payload.get("auto_import"):
            dest_dir = settings.MUSIC_DIR
            os.makedirs(dest_dir, exist_ok=True)

            safe_artist = sanitize_filename(extracted_artist)
            safe_title = sanitize_filename(extracted_title)
            dest_filename = f"{safe_artist} - {safe_title}.mp3"
            dest_filepath = os.path.join(dest_dir, dest_filename)

            # Avoid filename collisions
            counter = 1
            base_name, ext = os.path.splitext(dest_filename)
            while os.path.exists(dest_filepath):
                dest_filepath = os.path.join(dest_dir, f"{base_name} ({counter}){ext}")
                counter += 1

            shutil.move(converted_mp3_path, dest_filepath)
            final_filepath = dest_filepath

            # Index song into database
            try:
                song_data = extract_metadata(final_filepath)
                audio_features = analyze_audio_features(
                    final_filepath, total_duration=song_data.get("duration")
                )
                song_data.update(audio_features)

                with Session(target_engine) as session:
                    song_rec, _ = SongRepository.upsert_song(
                        session, song_data, source="existing_tag"
                    )
                    imported_song_id = song_rec.id
                    logger.info(
                        f"Successfully imported downloaded track ID {imported_song_id}: {final_filepath}"
                    )
            except Exception as import_err:  # noqa: BLE001
                logger.error(f"Failed to index downloaded track into DB: {import_err}")

        # 5. Update status -> DONE
        _update_download_job(
            target_engine,
            row_id,
            status="done",
            progress=100.0,
            file_path=final_filepath,
            imported_song_id=imported_song_id,
            completed_at=datetime.now(UTC),
        )

    except Exception as e:  # noqa: BLE001
        logger.error(f"Download job {job_id} failed: {e}")
        _update_download_job(
            target_engine,
            row_id,
            status="failed",
            error_message=str(e),
            completed_at=datetime.now(UTC),
        )
