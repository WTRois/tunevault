import io
import os
import shutil
from typing import Any

import mutagen
from loguru import logger
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, USLT
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from PIL import Image

from backend.core.config import settings
from backend.services.scanner import calculate_sha256


def convert_image_to_jpeg_bytes(image_bytes: bytes, quality: int = 85) -> bytes:
    """Convert input image bytes (PNG, WebP, JPEG) to JPEG format at specified quality."""
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def _backup_file(filepath: str) -> str:
    """Create a temporary backup file before mutating audio tags."""
    backup_path = f"{filepath}.bak"
    shutil.copy2(filepath, backup_path)
    return backup_path


def _restore_and_cleanup_backup(filepath: str, backup_path: str, success: bool) -> None:
    """Restore from backup on error or delete backup file on success."""
    if os.path.exists(backup_path):
        if not success:
            shutil.copy2(backup_path, filepath)
            logger.warning(f"Restored backup file for {filepath} due to tag write failure.")
        try:
            os.remove(backup_path)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Failed to remove temp backup file {backup_path}: {e}")


def restore_backup(filepath: str) -> bool:
    """Restore a file from its `.bak` backup (undo support, blueprint §16).

    The backup is kept so repeated undo stays possible; cleanup is the caller's job.
    """
    backup_path = f"{filepath}.bak"
    if not os.path.exists(backup_path):
        return False
    shutil.copy2(backup_path, filepath)
    return True


def _load_audio_mutagen(filepath: str) -> Any:
    """Load mutagen File object with graceful fallback to ID3 tags for MP3/AIFF files."""
    try:
        audio = mutagen.File(filepath)
        if audio is not None:
            return audio
    except Exception:  # noqa: BLE001, S110
        pass

    ext = filepath.lower()
    if ext.endswith((".mp3", ".aiff")):
        try:
            return ID3(filepath)
        except Exception:  # noqa: BLE001
            try:
                id3 = ID3()
                id3.save(filepath)
                return id3
            except Exception:  # noqa: BLE001, S110
                pass
    return None


def write_text_metadata(filepath: str, metadata: dict[str, Any]) -> str:
    """Write text metadata tags back to physical audio file and return updated SHA-256 hash."""
    backup_path = _backup_file(filepath)
    success = False

    try:
        audio = _load_audio_mutagen(filepath)
        if audio is None:
            raise ValueError(f"Unsupported or corrupted audio file: {filepath}")

        tags = audio.tags if hasattr(audio, "tags") and audio.tags is not None else audio
        if isinstance(tags, ID3) or isinstance(audio, ID3):
            target_id3 = tags if isinstance(tags, ID3) else audio
            if "title" in metadata and metadata["title"] is not None:
                target_id3.add(TIT2(encoding=3, text=str(metadata["title"])))
            if "artist" in metadata and metadata["artist"] is not None:
                target_id3.add(TPE1(encoding=3, text=str(metadata["artist"])))
            if "album" in metadata and metadata["album"] is not None:
                target_id3.add(TALB(encoding=3, text=str(metadata["album"])))
            if "album_artist" in metadata and metadata["album_artist"] is not None:
                target_id3.add(TPE2(encoding=3, text=str(metadata["album_artist"])))
            if "composer" in metadata and metadata["composer"] is not None:
                target_id3.add(TCOM(encoding=3, text=str(metadata["composer"])))
            if "genre" in metadata and metadata["genre"] is not None:
                target_id3.add(TCON(encoding=3, text=str(metadata["genre"])))
            if "year" in metadata and metadata["year"] is not None:
                target_id3.add(TDRC(encoding=3, text=str(metadata["year"])))
            if "track_number" in metadata and metadata["track_number"] is not None:
                target_id3.add(TRCK(encoding=3, text=str(metadata["track_number"])))
            if "disc_number" in metadata and metadata["disc_number"] is not None:
                target_id3.add(TPOS(encoding=3, text=str(metadata["disc_number"])))
            if "lyrics" in metadata and metadata["lyrics"] is not None:
                target_id3.add(USLT(encoding=3, lang="eng", desc="", text=str(metadata["lyrics"])))
            target_id3.save(filepath)

        elif isinstance(audio, FLAC):
            if "title" in metadata and metadata["title"] is not None:
                audio["TITLE"] = [str(metadata["title"])]
            if "artist" in metadata and metadata["artist"] is not None:
                audio["ARTIST"] = [str(metadata["artist"])]
            if "album" in metadata and metadata["album"] is not None:
                audio["ALBUM"] = [str(metadata["album"])]
            if "album_artist" in metadata and metadata["album_artist"] is not None:
                audio["ALBUMARTIST"] = [str(metadata["album_artist"])]
            if "composer" in metadata and metadata["composer"] is not None:
                audio["COMPOSER"] = [str(metadata["composer"])]
            if "genre" in metadata and metadata["genre"] is not None:
                audio["GENRE"] = [str(metadata["genre"])]
            if "year" in metadata and metadata["year"] is not None:
                audio["DATE"] = [str(metadata["year"])]
            if "track_number" in metadata and metadata["track_number"] is not None:
                audio["TRACKNUMBER"] = [str(metadata["track_number"])]
            if "disc_number" in metadata and metadata["disc_number"] is not None:
                audio["DISCNUMBER"] = [str(metadata["disc_number"])]
            if "lyrics" in metadata and metadata["lyrics"] is not None:
                audio["LYRICS"] = [str(metadata["lyrics"])]
            audio.save()

        elif isinstance(audio, MP4):
            if "title" in metadata and metadata["title"] is not None:
                audio["\xa9nam"] = [str(metadata["title"])]
            if "artist" in metadata and metadata["artist"] is not None:
                audio["\xa9ART"] = [str(metadata["artist"])]
            if "album" in metadata and metadata["album"] is not None:
                audio["\xa9alb"] = [str(metadata["album"])]
            if "album_artist" in metadata and metadata["album_artist"] is not None:
                audio["aART"] = [str(metadata["album_artist"])]
            if "composer" in metadata and metadata["composer"] is not None:
                audio["\xa9wrt"] = [str(metadata["composer"])]
            if "genre" in metadata and metadata["genre"] is not None:
                audio["\xa9gen"] = [str(metadata["genre"])]
            if "year" in metadata and metadata["year"] is not None:
                audio["\xa9day"] = [str(metadata["year"])]
            if "track_number" in metadata and metadata["track_number"] is not None:
                audio["trkn"] = [(int(metadata["track_number"]), 0)]
            if "disc_number" in metadata and metadata["disc_number"] is not None:
                audio["disk"] = [(int(metadata["disc_number"]), 0)]
            if "lyrics" in metadata and metadata["lyrics"] is not None:
                audio["\xa9lyr"] = [str(metadata["lyrics"])]
            audio.save()

        elif isinstance(audio, OggVorbis):
            if "title" in metadata and metadata["title"] is not None:
                audio["TITLE"] = [str(metadata["title"])]
            if "artist" in metadata and metadata["artist"] is not None:
                audio["ARTIST"] = [str(metadata["artist"])]
            if "album" in metadata and metadata["album"] is not None:
                audio["ALBUM"] = [str(metadata["album"])]
            if "genre" in metadata and metadata["genre"] is not None:
                audio["GENRE"] = [str(metadata["genre"])]
            if "year" in metadata and metadata["year"] is not None:
                audio["DATE"] = [str(metadata["year"])]
            if "lyrics" in metadata and metadata["lyrics"] is not None:
                audio["LYRICS"] = [str(metadata["lyrics"])]
            audio.save()

        else:
            audio.save()

        success = True
        return calculate_sha256(filepath)

    finally:
        _restore_and_cleanup_backup(filepath, backup_path, success)


def embed_cover_art(filepath: str, raw_image_bytes: bytes) -> tuple[str, str]:
    """Convert uploaded cover image to JPEG 85%, embed in audio file, update cache, and return (new_sha256, cover_cache_path)."""
    jpeg_bytes = convert_image_to_jpeg_bytes(raw_image_bytes, quality=85)
    backup_path = _backup_file(filepath)
    success = False

    try:
        audio = _load_audio_mutagen(filepath)
        if audio is None:
            raise ValueError(f"Unsupported or corrupted audio file: {filepath}")

        tags = audio.tags if hasattr(audio, "tags") and audio.tags is not None else audio

        if isinstance(tags, ID3) or isinstance(audio, ID3):
            target_id3 = tags if isinstance(tags, ID3) else audio
            apic_keys = [k for k in target_id3 if k.startswith("APIC")]
            for k in apic_keys:
                del target_id3[k]
            target_id3.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,  # Front cover
                    desc="Cover",
                    data=jpeg_bytes,
                )
            )
            target_id3.save(filepath)

        elif isinstance(audio, FLAC):
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = jpeg_bytes
            audio.add_picture(pic)
            audio.save()

        elif isinstance(audio, MP4):
            audio.tags["covr"] = [MP4Cover(jpeg_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

        else:
            audio.save()

        success = True
        new_sha256 = calculate_sha256(filepath)

        # Save to local cover storage cache
        os.makedirs(settings.resolved_covers_dir, exist_ok=True)
        cover_cache_path = os.path.join(settings.resolved_covers_dir, f"{new_sha256}.jpg")
        with open(cover_cache_path, "wb") as f:
            f.write(jpeg_bytes)

        return new_sha256, cover_cache_path

    finally:
        _restore_and_cleanup_backup(filepath, backup_path, success)


def remove_cover_art(filepath: str) -> str:
    """Remove embedded cover art tag from audio file and return updated SHA-256 hash."""
    backup_path = _backup_file(filepath)
    success = False

    try:
        audio = _load_audio_mutagen(filepath)
        if audio is None:
            raise ValueError(f"Unsupported or corrupted audio file: {filepath}")

        tags = audio.tags if hasattr(audio, "tags") and audio.tags is not None else audio

        if isinstance(tags, ID3) or isinstance(audio, ID3):
            target_id3 = tags if isinstance(tags, ID3) else audio
            apic_keys = [k for k in target_id3 if k.startswith("APIC")]
            for k in apic_keys:
                del target_id3[k]
            target_id3.save(filepath)

        elif isinstance(audio, FLAC):
            audio.clear_pictures()
            audio.save()

        elif isinstance(audio, MP4) and "covr" in audio.tags:
            del audio.tags["covr"]
            audio.save()

        else:
            audio.save()

        success = True
        return calculate_sha256(filepath)

    finally:
        _restore_and_cleanup_backup(filepath, backup_path, success)
