import os
from datetime import UTC, datetime

from loguru import logger
from sqlmodel import Session

from backend.database.session import engine
from backend.models.scan_job import ScanJob
from backend.services.analyzer import analyze_audio_features
from backend.services.file_indexer import index_file, save_audio_features
from backend.services.scanner import scan_directory


def run_scan_job(
    job_id: int,
    directory_path: str,
    perform_audio_analysis: bool = True,
    db_engine=None,
) -> None:
    """Execute asynchronous background directory scanning task."""
    target_engine = db_engine or engine

    with Session(target_engine) as session:
        job = session.get(ScanJob, job_id)
        if not job:
            return

        job.status = "running"
        session.add(job)
        session.commit()

        try:
            # 1. Scan directory for audio files
            audio_files = scan_directory(directory_path)
            job.total_files = len(audio_files)
            session.add(job)
            session.commit()

            added_count = 0
            updated_count = 0
            error_count = 0

            # 2. Process each audio file
            for filepath in audio_files:
                try:
                    if not os.path.exists(filepath):
                        error_count += 1
                        continue

                    # V2 fast pass (§33/§34): index into files/recordings/provenance;
                    # unchanged files skip extraction/hashing entirely.
                    file_row, extracted_meta, changed, created = index_file(session, filepath)

                    if not changed:
                        # Unchanged file — skip re-extraction and re-analysis.
                        job.scanned_files += 1
                        session.add(job)
                        session.commit()
                        continue

                    # Optional Librosa Audio Analysis (BPM & Musical Key)
                    if perform_audio_analysis:
                        audio_features = analyze_audio_features(
                            filepath,
                            total_duration=extracted_meta.get("duration"),
                        )
                        save_audio_features(session, file_row.id, audio_features)

                    # TV2-011b: the V2 schema is the only write path; the legacy
                    # songs table is no longer written (compat repo flip).
                    if created:
                        added_count += 1
                    else:
                        updated_count += 1

                except Exception as err:  # noqa: BLE001
                    logger.warning(f"Failed to process file {filepath}: {err}")
                    error_count += 1

                finally:
                    job.scanned_files += 1
                    job.added_count = added_count
                    job.updated_count = updated_count
                    job.error_count = error_count

                    # Periodically commit progress every 10 files
                    if job.scanned_files % 10 == 0:
                        session.add(job)
                        session.commit()

            # Mark ScanJob as completed
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.added_count = added_count
            job.updated_count = updated_count
            job.error_count = error_count
            session.add(job)
            session.commit()

        except Exception as err:  # noqa: BLE001
            logger.error(f"Scan job {job_id} failed: {err}")
            job.status = "failed"
            job.error_message = str(err)
            job.completed_at = datetime.now(UTC)
            session.add(job)
            session.commit()
