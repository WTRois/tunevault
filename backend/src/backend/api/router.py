from fastapi import APIRouter

from backend.api.endpoints import (
	analysis,
	artwork,
	downloader,
	events,
	export,
	health,
	identification,
	jobs,
	organization,
	scan,
	songs,
	stats,
)
from backend.core.config import settings

api_router = APIRouter()


@api_router.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint to verify backend service status."""
    return {
        "status": "ok",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


api_router.include_router(scan.router)
api_router.include_router(songs.router)
api_router.include_router(identification.router)
api_router.include_router(organization.router)
api_router.include_router(organization.change_sets_router)
api_router.include_router(artwork.router)
api_router.include_router(analysis.router)
api_router.include_router(jobs.router)
api_router.include_router(events.router)
api_router.include_router(health.router)
api_router.include_router(stats.router)
api_router.include_router(export.router)
api_router.include_router(downloader.router)
