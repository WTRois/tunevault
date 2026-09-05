import io
import os
from pathlib import Path
from typing import Any

import mutagen
from loguru import logger
from mutagen.flac import FLAC
from mutagen.id3 import APIC, ID3
from mutagen.mp4 import MP4
from PIL import Image

from backend.core.config import settings
from backend.services.scanner import calculate_sha256, get_file_system_metadata


def _parse_first_text(value: Any) -> str | None:
    """Helper to extract clean string from mutagen tag list/tuple."""
    if not value:
        return None
    if isinstance(value, (list, tuple)):
        return str(value[0]).strip() if value[0] else None
    return str(value).strip()


def _parse_int(value: Any) -> int | None:
    """Helper to safely parse integer values like year, track, disc."""
    if not value:
        return None
    try:
        val_str = _parse_first_text(value)
        if val_str:
            if "/" in val_str:
                val_str = val_str.split("/")[0]
            return int(val_str)
    except (ValueError, TypeError):
        pass
    return None


def _parse_musicbrainz_id(tags: Any) -> str | None:
    """Extract a MusicBrainz recording MBID from ID3 TXXX / FLAC/Vorbis tags."""
    candidates = []
    getter = getattr(tags, "get", None)
    if getter:
        candidates.extend(
            [
                getter("TXXX:MusicBrainz Track Id"),
                getter("musicbrainz_trackid"),
                getter("----:com.apple.iTunes:MusicBrainz Track Id"),
            ]
        )
    for value in candidates:
        text = _parse_first_text(value)
        if not text:
            continue
        mbid = text.rsplit("/", 1)[-1].strip()
        if mbid:
            return mbid
    return None


def extract_cover_art(audio: mutagen.File, sha256_hash: str) -> bool:
    """Extract embedded cover art from audio file and save to covers directory."""
    if not audio:
        return False

    cover_bytes: bytes | None = None

    try:
        if hasattr(audio, "tags") and audio.tags:
            tags = audio.tags
            if isinstance(tags, ID3):
                for tag in tags.values():
                    if isinstance(tag, APIC):
                        cover_bytes = tag.data
                        break

            elif isinstance(audio, FLAC) and audio.pictures:
                cover_bytes = audio.pictures[0].data

            elif isinstance(audio, MP4) and "covr" in audio.tags:
                covers = audio.tags["covr"]
                if covers:
                    cover_bytes = bytes(covers[0])

            elif hasattr(tags, "get") and "metadata_block_picture" in tags:
                from mutagen.flac import Picture

                pic_data = tags["metadata_block_picture"][0]
                picture = Picture(bytes.fromhex(pic_data))
                cover_bytes = picture.data

        if cover_bytes:
            os.makedirs(settings.resolved_covers_dir, exist_ok=True)
            output_path = os.path.join(settings.resolved_covers_dir, f"{sha256_hash}.jpg")

            image = Image.open(io.BytesIO(cover_bytes))
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(output_path, "JPEG", quality=85)
            return True

    except Exception as e:  # noqa: BLE001
        logger.debug(f"Cover art extraction skipped: {e}")

    return False


def extract_metadata(filepath: str) -> dict[str, Any]:
    """Extract complete metadata (system, basic, technical, and cover art) from an audio file."""
    sys_meta = get_file_system_metadata(filepath)
    sha256_hash = calculate_sha256(filepath)
    ext = Path(filepath).suffix.lower()

    meta: dict[str, Any] = {
        "filename": sys_meta["filename"],
        "filepath": sys_meta["filepath"],
        "file_size": sys_meta["file_size"],
        "sha256": sha256_hash,
        "codec": ext.lstrip("."),
        "title": None,
        "artist": None,
        "album": None,
        "album_artist": None,
        "composer": None,
        "genre": None,
        "year": None,
        "track_number": None,
        "disc_number": None,
        "duration": None,
        "bitrate": None,
        "sample_rate": None,
        "channels": None,
        "lyrics": None,
        "has_cover": False,
    }

    try:
        audio = mutagen.File(filepath)
        if audio is not None:
            if hasattr(audio, "info") and audio.info is not None:
                info = audio.info
                meta["duration"] = getattr(info, "length", None)
                meta["bitrate"] = getattr(info, "bitrate", None)
                meta["sample_rate"] = getattr(info, "sample_rate", None)
                meta["channels"] = getattr(info, "channels", None)
                codec_attr = getattr(info, "codec", None)
                if codec_attr:
                    meta["codec"] = str(codec_attr).lower()

            tags = audio.tags if hasattr(audio, "tags") and audio.tags else audio

            if tags:

                def get_tag(*keys: str) -> Any | None:
                    for k in keys:
                        if k in tags:
                            return tags[k]
                    return None

                meta["title"] = _parse_first_text(get_tag("TIT2", "title", "\xa9nam", "TITLE"))
                meta["artist"] = _parse_first_text(get_tag("TPE1", "artist", "\xa9ART", "ARTIST"))
                meta["album"] = _parse_first_text(get_tag("TALB", "album", "\xa9alb", "ALBUM"))
                meta["album_artist"] = _parse_first_text(
                    get_tag("TPE2", "albumartist", "aART", "ALBUMARTIST")
                )
                meta["composer"] = _parse_first_text(
                    get_tag("TCOM", "composer", "\xa9wrt", "COMPOSER")
                )
                meta["genre"] = _parse_first_text(get_tag("TCON", "genre", "\xa9gen", "GENRE"))
                meta["year"] = _parse_int(
                    get_tag("TDRC", "TYER", "date", "\xa9day", "DATE", "YEAR")
                )
                meta["track_number"] = _parse_int(
                    get_tag("TRCK", "tracknumber", "trkn", "TRACKNUMBER")
                )
                meta["disc_number"] = _parse_int(
                    get_tag("TPOS", "discnumber", "disk", "DISCNUMBER")
                )
                meta["lyrics"] = _parse_first_text(get_tag("USLT", "lyrics", "\xa9lyr", "LYRICS"))
                meta["musicbrainz_recording_id"] = _parse_musicbrainz_id(tags)

            meta["has_cover"] = extract_cover_art(audio, sha256_hash)

    except Exception as err:  # noqa: BLE001
        logger.warning(f"Error parsing metadata for {filepath}: {err}")

    return meta
