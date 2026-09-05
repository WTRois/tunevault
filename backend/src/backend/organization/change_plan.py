"""Safe Change Plan (blueprint §15) — boundary between intelligence and FS.

A plan is *pure data*: building and previewing never touches the filesystem.
Applying (TV2-026) is the only mutation path and honours ORGANIZE_DRY_RUN.
"""

from sqlmodel import Session, select

from backend.core.config import settings
from backend.models import Change, ChangeSet, File, MetadataProvenance
from backend.models.metadata import PROVENANCE_PRIORITY
from backend.organization.naming import build_target_path

# Fields the §15 plan may change (metadata_changes keys → new tag values).
PLAN_METADATA_FIELDS = ("artist", "title", "album", "album_artist", "year", "track_number", "disc_number")


def _provenance_values(
    session: Session, file_id: int, *, source: str | None = None
) -> dict[str, str | None]:
    """Canonical provenance values for a file.

    ``source=None`` resolves every field by §9 priority (latest row wins
    ties); ``source="existing_tag"`` reads only what the file's own tags
    reported — the pre-change side of the §15 diff.
    """
    rows = session.exec(
        select(MetadataProvenance).where(MetadataProvenance.file_id == file_id)
    ).all()
    best: dict[str, tuple[int, int, str]] = {}
    for row in rows:  # ordered by id → later rows of equal priority win
        if source is not None and row.source != source:
            continue
        key = (PROVENANCE_PRIORITY.get(row.source, 0), row.id or 0)
        current = best.get(row.field_name)
        if current is None or key > (current[0], current[1]):
            best[row.field_name] = (*key, row.value_text)
    return {name: value[2] for name, value in best.items()}


def build_change_plan(session: Session, file: File) -> dict | None:
    """Build the §15 change plan for one file. None when nothing to change."""
    file_id = file.id or 0
    resolved = _provenance_values(session, file_id)
    if not resolved:
        return None  # identification has not been applied yet
    current = _provenance_values(session, file_id, source="existing_tag")

    metadata_changes: dict[str, list] = {}
    for field in PLAN_METADATA_FIELDS:
        old = current.get(field)
        new = resolved.get(field)
        if field == "year":
            try:
                new = int(new) if new is not None else None
            except ValueError:
                new = None
        if field in ("track_number", "disc_number"):
            try:
                new = int(new) if new is not None else None
            except ValueError:
                new = None
        if (old or None) != (new or None):
            metadata_changes[field] = [old, new]

    new_path = build_target_path(
        album_artist=resolved.get("album_artist") or resolved.get("artist"),
        year=metadata_changes.get("year", [None, current.get("year")])[1]
        or current.get("year"),
        album=resolved.get("album") or current.get("album"),
        track=metadata_changes.get("track_number", [None, current.get("track_number")])[1]
        or current.get("track_number"),
        title=resolved.get("title") or current.get("title"),
        disc=metadata_changes.get("disc_number", [None, current.get("disc_number")])[1]
        or current.get("disc_number"),
        ext=file.extension,
        artist=resolved.get("artist"),
        release_country=resolved.get("release_country"),
        catalog_number=resolved.get("catalog_number"),
    )

    confidence = _plan_confidence(session, file_id)

    return {
        "file_id": file_id,
        "old_path": file.filepath,
        "new_path": str(new_path),
        "metadata_changes": metadata_changes or None,
        "artwork": None,  # artwork pipeline lands with TV2-021..023
        "confidence": confidence,
        "dry_run": settings.ORGANIZE_DRY_RUN,
    }


def _plan_confidence(session: Session, file_id: int) -> float:
    """Mean provenance confidence for the file (0.0 when unknown)."""
    rows = session.exec(
        select(MetadataProvenance).where(MetadataProvenance.file_id == file_id)
    ).all()
    if not rows:
        return 0.0
    return float(sum(float(row.confidence) for row in rows) / len(rows))


def preview_plans(session: Session, file_ids: list[int]) -> dict:
    """Build plans for many files. Read-only: no FS access, no rows written."""
    plans = []
    for file_id in file_ids:
        file = session.get(File, file_id)
        if file is None:
            plans.append({"file_id": file_id, "error": "file not found"})
            continue
        plan = build_change_plan(session, file)
        if plan is None:
            plans.append({"file_id": file_id, "skipped": "no accepted metadata to apply"})
        else:
            plans.append(plan)
    return {"plans": plans, "dry_run": settings.ORGANIZE_DRY_RUN}


def persist_change_set(session: Session, plans: list[dict], name: str) -> ChangeSet:
    """Persist a preview as a pending change set (applied by TV2-026)."""
    change_set = ChangeSet(name=name, status="pending", created_by="preview")
    session.add(change_set)
    session.commit()
    session.refresh(change_set)

    for plan in plans:
        if "error" in plan or "skipped" in plan:
            continue
        changes = plan.get("metadata_changes") or {}
        session.add(
            Change(
                change_set_id=change_set.id or 0,
                file_id=plan["file_id"],
                operation="metadata_update",
                old_value_json=_json({key: pair[0] for key, pair in changes.items()}),
                new_value_json=_json({key: pair[1] for key, pair in changes.items()}),
                old_path=plan.get("old_path"),
                new_path=plan.get("new_path"),
                verification_status="pending",
            )
        )
    session.commit()
    return change_set


def _json(value) -> str | None:
    import json

    if value is None:
        return None
    return json.dumps(value, default=str)