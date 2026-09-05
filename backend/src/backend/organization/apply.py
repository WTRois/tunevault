"""Apply + verify + undo engine for change sets (blueprint §16, TV2-026).

Never Destroy (§2.4): the apply path is copy-first — the original file is
never removed until the moved copy is verified (readable + hash match), and
a byte-identical backup is kept for undo.

Undo rules (§16, followed verbatim):
    - Undo metadata: restore old tag snapshot (the backup file).
    - Undo rename/move: restore old path.
    - Undo whole change set: rollback atomically as far as the filesystem
      allows (per-file rollback, reverse order).
    - Never delete the only copy of a file as part of an automatic
      clean-up operation.
"""

import json
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from sqlmodel import Session, select

from backend.core.config import settings
from backend.core.paths import (
    validate_read,
    validate_write,
)
from backend.core.time import now_utc
from backend.models import Change, ChangeSet, File
from backend.organization import backup as backup_store
from backend.organization.naming import resolve_collision
from backend.services.file_indexer import save_tag_provenance
from backend.services.scanner import calculate_sha256
from backend.services.tag_writer import write_text_metadata

# Values written to files must stay within the §15 plan fields.
APPLY_TAG_FIELDS = (
    "artist", "title", "album", "album_artist", "composer", "genre",
    "year", "track_number", "disc_number",
)


def _music_root() -> Path:
    return Path(settings.MUSIC_DIR).expanduser().resolve()


def _sha_of(path: str) -> str | None:
    """Hash an existing file; None when unreadable (never raises)."""
    try:
        return calculate_sha256(path)
    except Exception:  # noqa: BLE001
        return None


def _verify_file(path: str, expected_sha: str | None) -> bool:
    """Post-move verification (§16): readable + hash match."""
    try:
        with open(path, "rb") as f:
            f.read(1)
    except OSError:
        return False
    if expected_sha is None:
        return True
    return _sha_of(path) == expected_sha


def apply_change_set(
    session: Session,
    change_set_id: int,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Apply a pending change set. Copy-first, verify, then remove originals.

    While ``ORGANIZE_DRY_RUN`` is set the engine performs NO filesystem and
    NO database mutations and marks the change set ``dry_run`` (§15).
    """
    cs = session.get(ChangeSet, change_set_id)
    if cs is None:
        return {"change_set_id": change_set_id, "error": "change set not found"}
    if cs.status != "pending":
        return {"change_set_id": change_set_id, "error": f"change set status is '{cs.status}'"}

    if settings.ORGANIZE_DRY_RUN:
        cs.status = "dry_run"
        session.add(cs)
        session.commit()
        return {
            "change_set_id": change_set_id,
            "dry_run": True,
            "applied": 0,
            "failed": 0,
            "skipped": 0,
        }

    changes = session.exec(
        select(Change).where(Change.change_set_id == change_set_id).order_by(Change.id)
    ).all()

    applied, failed, skipped = 0, 0, 0
    for index, change in enumerate(changes):
        try:
            outcome = _apply_one(session, cs, change)
        except Exception as err:  # noqa: BLE001
            logger.error(f"Change {change.id} failed: {err}")
            change.verification_status = "failed"
            session.add(change)
            session.commit()
            outcome = "failed"
        if outcome == "applied":
            applied += 1
        elif outcome == "failed":
            failed += 1
        else:
            skipped += 1
        if progress_cb is not None:
            progress_cb(index + 1, len(changes), outcome)

    cs.status = "applied" if failed == 0 else "partial"
    if applied == 0 and failed > 0:
        cs.status = "failed"
    if applied > 0:
        cs.applied_at = now_utc()
    session.add(cs)
    session.commit()

    return {
        "change_set_id": change_set_id,
        "dry_run": False,
        "applied": applied,
        "failed": failed,
        "skipped": skipped,
    }


def _apply_one(session: Session, cs: ChangeSet, change: Change) -> str:
    """Apply a single change. Returns 'applied' | 'duplicate' | 'failed' | 'skipped'."""
    file = session.get(File, change.file_id)
    if file is None:
        change.verification_status = "failed"
        session.add(change)
        session.commit()
        return "failed"

    old_path = change.old_path or file.filepath
    if not os.path.exists(old_path):
        change.verification_status = "skipped"
        session.add(change)
        session.commit()
        return "skipped"

    # §27.4 sandbox: both ends of the move must stay inside the roots.
    validate_read(old_path)

    # 1. Backup (§16 copy-first) — byte-identical snapshot for undo.
    #    CREATE_BACKUPS=false skips the artifact (undo will then fail per change).
    backup_path = (
        backup_store.save_backup(cs.id or 0, change.id or 0, old_path)
        if settings.CREATE_BACKUPS
        else None
    )

    # 2. Write new metadata tags (§15 metadata_changes → file tags).
    new_values = json.loads(change.new_value_json) if change.new_value_json else None
    if new_values:
        filtered = {k: v for k, v in new_values.items() if k in APPLY_TAG_FIELDS and v is not None}
        if filtered:
            write_text_metadata(old_path, filtered)
    post_tag_sha = calculate_sha256(old_path)

    # 3. Move (copy-first): target from the plan, resolved against MUSIC_DIR.
    relative = change.new_path or ""
    target = str(_music_root() / relative) if relative else old_path
    target, collision = resolve_collision(target, post_tag_sha, _sha_of)
    validate_write(target)

    os.makedirs(os.path.dirname(target), exist_ok=True)

    if collision == "duplicate":
        # Identical content already exists at the target (§17): never copy
        # again, never delete anything. Point the DB at the existing file.
        _sync_file_row(session, file, target, post_tag_sha, new_values)
        change.verification_status = "duplicate"
        change.new_path = target
        session.add(change)
        session.commit()
        return "duplicate"

    shutil.copy2(old_path, target)
    if not _verify_file(target, post_tag_sha):
        # Verification failed: remove the *copy* (the original is intact)
        # and record the failure — the library is untouched.
        os.remove(target)
        change.verification_status = "verify_failed"
        session.add(change)
        session.commit()
        logger.warning(f"Verification failed for {target}; original kept at {old_path}")
        return "failed"

    # Verified copy exists → now (and only now) remove the original.
    os.remove(old_path)

    change.new_path = target
    change.backup_path = backup_path
    change.verification_status = "verified"
    session.add(change)
    _sync_file_row(session, file, target, post_tag_sha, new_values)
    session.commit()
    return "applied"


def _sync_file_row(
    session: Session, file: File, new_path: str, new_sha: str, new_values: dict | None
) -> None:
    """Point the file row at its new location and refresh tag-side provenance."""
    file.filepath = new_path
    file.sha256 = new_sha
    if os.path.exists(new_path):
        file.file_size = os.path.getsize(new_path)
        file.modified_at = datetime.fromtimestamp(os.path.getmtime(new_path), tz=UTC)
    file.updated_at = now_utc()
    session.add(file)
    if new_values:
        # The physical tags now carry the applied values — existing_tag
        # provenance rows must say so (same-source update, §9-safe).
        save_tag_provenance(session, file.id or 0, new_values, source="existing_tag")


def undo_change_set(
    session: Session,
    change_set_id: int,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Roll a change set back (§16). Restores bytes and paths from backups.

    Per change (reverse order): copy the backup back to the old path, verify
    it, then remove the moved file — two copies exist at every deletion.
    """
    cs = session.get(ChangeSet, change_set_id)
    if cs is None:
        return {"change_set_id": change_set_id, "error": "change set not found"}
    if cs.status not in ("applied", "partial", "failed"):
        return {"change_set_id": change_set_id, "error": f"change set status is '{cs.status}'"}

    changes = session.exec(
        select(Change)
        .where(Change.change_set_id == change_set_id)
        .order_by(Change.id.desc())
    ).all()

    undone, failed = 0, 0
    for index, change in enumerate(changes):
        try:
            outcome = _undo_one(session, change)
        except Exception as err:  # noqa: BLE001
            logger.error(f"Undo of change {change.id} failed: {err}")
            outcome = "failed"
        if outcome == "undone":
            undone += 1
        elif outcome == "failed":
            failed += 1
        if progress_cb is not None:
            progress_cb(index + 1, len(changes), outcome)

    cs.status = "rolled_back" if failed == 0 and undone > 0 else "rollback_failed"
    if undone > 0:
        cs.rolled_back_at = now_utc()
    session.add(cs)
    session.commit()

    return {"change_set_id": change_set_id, "undone": undone, "failed": failed}


def _undo_one(session: Session, change: Change) -> str:
    """Restore one change. Returns 'undone' | 'failed' | 'skipped'."""
    if change.verification_status not in ("verified", "duplicate"):
        return "skipped"  # nothing durable was applied to this file

    file = session.get(File, change.file_id)
    backup_path = change.backup_path
    if file is None or not backup_path or not os.path.exists(backup_path):
        logger.warning(f"Undo skipped for change {change.id}: no backup artifact")
        return "failed"

    backup_sha = calculate_sha256(backup_path)
    old_path = change.old_path
    if not old_path:
        return "failed"

    # Restore the original bytes at the original path (§16 undo rules).
    os.makedirs(os.path.dirname(old_path), exist_ok=True)
    validate_write(old_path)
    shutil.copy2(backup_path, old_path)
    if not _verify_file(old_path, backup_sha):
        logger.warning(f"Undo verification failed for {old_path}")
        return "failed"

    # Original restored and verified → remove the moved/mutated file.
    current_path = change.new_path
    if current_path and os.path.exists(current_path) and os.path.abspath(current_path) != os.path.abspath(old_path):
        os.remove(current_path)

    old_values = json.loads(change.old_value_json) if change.old_value_json else None
    change.verification_status = "rolled_back"
    session.add(change)

    file.filepath = old_path
    file.sha256 = backup_sha
    if os.path.exists(old_path):
        file.file_size = os.path.getsize(old_path)
    file.updated_at = now_utc()
    session.add(file)
    if old_values:
        save_tag_provenance(session, file.id or 0, old_values, source="existing_tag")
    session.commit()
    return "undone"