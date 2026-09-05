"""Backup artifacts for the organization undo path (blueprint §16, TV2-026).

Backups are file copies stored under ``STORAGE_DIR/backups/{change_set_id}/``;
the authoritative record of what was backed up lives in the ``changes`` rows
(``backup_path`` column) — the manifest IS the change set (§5.15).
Never delete the only copy of a file as part of an automatic operation (§16).
"""

import os
import shutil

from backend.core.config import settings


def backup_root(change_set_id: int) -> str:
    """Directory holding all backups of one change set."""
    return os.path.join(settings.STORAGE_DIR, "backups", str(change_set_id))


def save_backup(change_set_id: int, change_id: int, source_path: str) -> str:
    """Copy the source file into the change set's backup area (§16 copy-first).

    Returns the backup path. The original file is never touched here.
    """
    root = backup_root(change_set_id)
    os.makedirs(root, exist_ok=True)
    extension = os.path.splitext(source_path)[1]
    backup_path = os.path.join(root, f"{change_id}{extension}")
    shutil.copy2(source_path, backup_path)
    return backup_path


def remove_backup(change_set_id: int, backup_path: str) -> None:
    """Delete one backup artifact (only safe once the original is restored)."""
    root = os.path.abspath(backup_root(change_set_id))
    target = os.path.abspath(backup_path)
    if os.path.commonpath([root, target]) != root:
        raise ValueError(f"Refusing to delete outside the backup area: {backup_path}")
    if os.path.exists(target):
        os.remove(target)