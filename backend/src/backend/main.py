import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from backend.api.router import api_router
from backend.core.config import settings, validate_startup
from backend.core.logging import setup_logging
from backend.database.session import init_db
from backend.services.downloader import cleanup_temp_downloads

setup_logging()


async def _download_cleanup_loop() -> None:
    """Remove temporary downloader files periodically without blocking requests."""
    while True:
        try:
            await asyncio.to_thread(cleanup_temp_downloads)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Download cleanup failed: {err}")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate config, apply database migrations, run periodic cleanup."""
    validate_startup()  # §38 fail fast on missing required config
    try:
        init_db()
        logger.info("Database migrations applied successfully.")
    except Exception as err:  # noqa: BLE001
        logger.error(f"Failed to apply database migrations on startup: {err}")

    cleanup_task = asyncio.create_task(_download_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS origins come from settings (CORS_ORIGINS env) — never a hardcoded wildcard (§27.3)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router, prefix=settings.API_V1_STR)


# Global Exception Handlers with explicit CORS header fallback
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    headers = {"Access-Control-Allow-Origin": "*"}
    if exc.headers:
        headers.update(exc.headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTPException",
            "message": exc.detail,
            "status": exc.status_code,
        },
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.url}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "ValidationError",
            "message": "Input validation failed",
            "detail": exc.errors(),
            "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
        },
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error on {request.url}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": str(exc)
            if settings.PROJECT_NAME == "TuneVault"
            else "An unexpected error occurred.",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
        },
    )


@app.get("/")
def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME} API",
        "docs": "/docs",
        "health": f"{settings.API_V1_STR}/health",
    }


def main():
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
