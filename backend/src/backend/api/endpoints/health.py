"""Library health API (blueprint §14 + §18 Health, TV2-033).

    GET /api/library/health           — the §14 metrics response
    GET /api/library/issues/{type}   — drill-down rows for §22 review lists
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from backend.database.session import get_session
from backend.intelligence.health import ISSUE_TYPES, compute_library_health, issue_rows

router = APIRouter(prefix="/library", tags=["Library Health"])


@router.get("/health")
def library_health(session: Session = Depends(get_session)):
    return compute_library_health(session)


@router.get("/issues/{issue_type}")
def library_issues(issue_type: str, session: Session = Depends(get_session)):
    if issue_type not in ISSUE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown issue type {issue_type!r}. Valid: {', '.join(ISSUE_TYPES)}",
        )
    return issue_rows(session, issue_type)