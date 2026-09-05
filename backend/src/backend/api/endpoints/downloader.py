from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session

from backend.database.session import get_session
from backend.schemas.downloader import (
    DownloadJobCreate,
    DownloadJobStatusResponse,
    DownloadPreviewRequest,
    DownloadPreviewResponse,
)
from backend.services.downloader import (
    create_download_job,
    delete_download_job,
    fetch_url_preview,
    get_download_job,
    process_download_job,
)

router = APIRouter(prefix="/download", tags=["YT Music Downloader"])


@router.post("/preview", response_model=DownloadPreviewResponse)
def get_video_preview(payload: DownloadPreviewRequest):
    """Extract metadata preview (title, artist, album, thumbnail) from YouTube URL."""
    try:
        return fetch_url_preview(payload.url.strip())
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memproses metadata preview: {err}",
        ) from err


@router.post("", response_model=DownloadJobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def start_audio_download(
    payload: DownloadJobCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Start background audio download and conversion job."""
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL harus diawali dengan http:// atau https://",
        )

    if payload.bitrate not in (128, 192, 256, 320):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bitrate harus salah satu dari: 128, 192, 256, 320 kbps.",
        )

    db_engine = session.get_bind()
    job_id = create_download_job(payload, db_engine=db_engine)

    background_tasks.add_task(
        process_download_job,
        job_id=job_id,
        db_engine=db_engine,
    )

    job_data = get_download_job(job_id, db_engine=db_engine)
    if not job_data:
        raise HTTPException(status_code=500, detail="Gagal membuat download job.")

    return DownloadJobStatusResponse(**job_data)


@router.get("/jobs/{job_id}", response_model=DownloadJobStatusResponse)
def get_download_job_status(job_id: str, session: Session = Depends(get_session)):
    """Retrieve real-time progress and status of a download job."""
    job_data = get_download_job(job_id, db_engine=session.get_bind())
    if not job_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Download job dengan ID '{job_id}' tidak ditemukan.",
        )

    return DownloadJobStatusResponse(**job_data)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_download_job(job_id: str, session: Session = Depends(get_session)):
    """Delete a finished or failed download job record."""
    success = delete_download_job(job_id, db_engine=session.get_bind())
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Download job dengan ID '{job_id}' tidak ditemukan.",
        )
