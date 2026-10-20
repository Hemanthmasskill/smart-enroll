from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.agents.tools import list_agent_activity
from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.agent import AuditEventRecord

router = APIRouter()


@router.get(
    "/activity",
    response_model=list[AuditEventRecord],
    tags=["Agent Orchestration"],
)
def get_agent_activity_endpoint(
    applicationId: str | None = Query(None, description="Filter by application ID"),
    stage: str | None = Query(None, description="Filter by workflow stage"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve observable agent activity audit log entries.
    Admins can query across all applications.
    Applicants can query only their own application.
    """
    return list_agent_activity(
        db=db,
        current_user=current_user,
        application_id=applicationId,
        stage=stage,
        status=status,
        limit=limit,
    )


@router.get(
    "/activity/{application_id}",
    response_model=list[AuditEventRecord],
    tags=["Agent Orchestration"],
)
def get_application_agent_activity_endpoint(
    application_id: str,
    stage: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve observable agent activity for a specific application.
    Enforces ownership checks for applicants.
    """
    return list_agent_activity(
        db=db,
        current_user=current_user,
        application_id=application_id,
        stage=stage,
        status=status,
        limit=limit,
    )
