"""Standalone worker process: polls the SQLite job queue (blueprint §23).

Run with::

    uv run python -m backend.workers.worker
"""

import time

from loguru import logger
from sqlmodel import Session

from backend.core.config import settings, validate_startup
from backend.core.logging import setup_logging
from backend.database.session import engine
from backend.repositories.job_repository import JobRepository, claim_next_pending
from backend.workers.handlers.analyze import handle_analyze
from backend.workers.handlers.identify import handle_identify
from backend.workers.handlers.organize import handle_organize
from backend.workers.handlers.scan import handle_scan

HANDLERS = {
    "scan": handle_scan,
    "identify": handle_identify,
    "organize": handle_organize,
    "analyze_audio": handle_analyze,
}

POLL_INTERVAL_SECONDS = settings.JOB_POLL_INTERVAL_MS / 1000.0


def process_one_job() -> bool:
    """Claim and run a single job. Returns True when a job was processed."""
    with Session(engine) as session:
        job = claim_next_pending(session, list(HANDLERS))
        if job is None:
            return False

        # §36 job lifecycle: structured fields on every log line.
        started = time.perf_counter()
        log = logger.bind(operation="job", job_id=job.id, job_type=job.job_type)
        log.info(f"Worker claimed job {job.id} (type={job.job_type})")
        try:
            handler = HANDLERS.get(job.job_type)
            if handler is None:
                raise ValueError(f"No handler registered for job type '{job.job_type}'")
            result = handler(session, job)
            JobRepository.mark_completed(session, job.id, result)
            log.bind(
                status="completed", duration_ms=round((time.perf_counter() - started) * 1000)
            ).info(f"Job {job.id} completed")
        except Exception as err:  # noqa: BLE001
            log.bind(
                status="failed",
                error_code=type(err).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000),
            ).error(f"Job {job.id} failed: {err}")
            JobRepository.mark_failed(session, job.id, str(err))
        return True


def run_forever() -> None:
    setup_logging()
    validate_startup()  # §38 fail fast on missing required config
    logger.info(
        f"TuneVault worker started; polling job queue every {settings.JOB_POLL_INTERVAL_MS}ms"
    )
    while True:
        try:
            processed = process_one_job()
        except KeyboardInterrupt:
            logger.info("Worker stopped")
            return
        except Exception as err:  # noqa: BLE001
            logger.error(f"Worker loop error: {err}")
            processed = False
        time.sleep(0 if processed else POLL_INTERVAL_SECONDS)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()