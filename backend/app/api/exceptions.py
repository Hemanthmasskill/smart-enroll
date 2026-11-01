import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pymongo.database import Database

from app.api.deps import RequireRole, get_current_user
from app.core.database import get_db
from app.core.rate_limit import enforce_rate_limit
from app.schemas.exceptions import (
    ExceptionListResponse,
    ExceptionResolveRequest,
    ExceptionResponse,
)
from app.services.exceptions import (
    get_exception_by_id,
    list_exceptions,
    list_my_exceptions,
    resolve_exception,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=list[ExceptionResponse],
    status_code=status.HTTP_200_OK,
    summary="List all exceptions (Admin only)",
)
def get_exceptions_list(
    status: Optional[str] = Query(None, description="Filter by status (OPEN, MONITORING, RESOLVED, ALL)"),
    severity: Optional[str] = Query(None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW, ALL)"),
    type: Optional[str] = Query(None, description="Filter by exception type"),
    applicationId: Optional[str] = Query(None, description="Filter by application ID"),
    limit: int = Query(100, ge=1, le=100),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(RequireRole(["admin"])),
    db: Database = Depends(get_db),
):
    """
    Retrieve exception records with optional status, severity, type, and application filters.
    Strictly restricted to administrative users.
    """
    items, _ = list_exceptions(
        db=db,
        current_user=current_user,
        status_filter=status,
        severity_filter=severity,
        type_filter=type,
        application_id=applicationId,
        limit=limit,
        skip=skip,
    )
    return items


@router.get(
    "/me",
    response_model=list[ExceptionResponse],
    status_code=status.HTTP_200_OK,
    summary="List authenticated applicant's own exceptions",
)
def get_my_exceptions(
    status: Optional[str] = Query(None, description="Filter by status (OPEN, MONITORING, RESOLVED, ALL)"),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve exceptions linked to the authenticated applicant's account.
    Enforces strict user isolation.
    """
    items, _ = list_my_exceptions(
        db=db,
        current_user=current_user,
        status_filter=status,
        limit=limit,
        skip=skip,
    )
    return items


@router.get(
    "/{exception_id}",
    response_model=ExceptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get exception details by ID",
)
def get_exception_detail(
    exception_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve detailed exception record.
    Admins can view any exception. Applicants are strictly authorized to view only their own.
    """
    return get_exception_by_id(db=db, exception_id=exception_id, current_user=current_user)


@router.post(
    "/{exception_id}/resolve",
    response_model=ExceptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve an exception (Admin only)",
)
def post_resolve_exception(
    exception_id: str,
    body: ExceptionResolveRequest,
    current_user: dict = Depends(RequireRole(["admin"])),
    db: Database = Depends(get_db),
):
    """
    Resolve an active exception with a mandatory, non-empty justification reason.
    Enforces:
    - Admin authorization.
    - Rate-limiting protection.
    - Precondition checks for missing documents.
    - Procedural discrepancy clearance and audit recording.
    - Safe resumption of downstream agent orchestration.
    """
    user_id = str(current_user.get("_id") or current_user.get("id"))
    enforce_rate_limit(
        f"exception_resolve:{user_id}",
        max_requests=30,
        window_seconds=60,
        action_description="exception resolution requests",
    )

    return resolve_exception(
        db=db,
        exception_id=exception_id,
        resolution_reason=body.resolutionReason,
        admin_user=current_user,
        resume_workflow=True,
    )

