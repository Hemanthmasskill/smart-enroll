from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.database import Database

from app.agents.tools import list_agent_activity
from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.agent import (
    AgentSystemStatusResponse,
    AuditEventRecord,
    OrchestrationRunResponse,
)

router = APIRouter()


@router.get(
    "/system-status",
    response_model=AgentSystemStatusResponse,
    tags=["Agent Orchestration"],
)
def get_agent_system_status():
    """
    Retrieve sanitized system status of the agent orchestrator and LLM provider configuration.
    Strictly excludes API keys, secrets, or internal credentials.
    """
    from app.agents.providers import is_local_endpoint
    from app.agents.tools import TOOL_REGISTRY
    from app.core.config import settings

    is_local = is_local_endpoint(settings.LLM_API_BASE)
    llm_enabled = settings.LLM_PROVIDER in ("openai_compatible", "openai")

    return AgentSystemStatusResponse(
        llmProvider=settings.LLM_PROVIDER,
        llmEnabled=llm_enabled,
        llmModel=settings.LLM_MODEL,
        isLocalEndpoint=is_local,
        allowLocalEndpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
        fallbackEnabled=settings.LLM_FALLBACK_TO_DETERMINISTIC,
        timeoutSeconds=settings.LLM_TIMEOUT_SECONDS,
        temperature=settings.LLM_TEMPERATURE,
        availableToolsCount=len(TOOL_REGISTRY),
        registeredTools=sorted(list(TOOL_REGISTRY.keys())),
    )


@router.get(
    "/runs",
    response_model=list[OrchestrationRunResponse],
    tags=["Agent Orchestration"],
)
def list_orchestration_runs(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve recent orchestration runs.
    Admin can view across all applications.
    Applicants can view only runs for their own application.
    Any unsupported or unexpected role is rejected with HTTP 403.
    """
    role = current_user.get("role")
    if role not in ("admin", "applicant"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: insufficient role permissions to view orchestration runs.",
        )

    query = {}
    if role == "applicant":
        app = db["applications"].find_one({"userId": str(current_user["_id"])})
        if not app:
            return []
        query["applicationId"] = app.get("applicationId")

    cursor = db["orchestration_runs"].find(query, {"_id": 0}).sort("startedAt", -1).limit(limit)
    return [OrchestrationRunResponse.model_validate(doc) for doc in cursor]


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


@router.post(
    "/orchestrate/{application_id}",
    response_model=OrchestrationRunResponse,
    tags=["Agent Orchestration"],
)
def orchestrate_application_endpoint(
    application_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Trigger autonomous agent orchestration loop for an application.
    Enforces RBAC: Applicants may only orchestrate their own application;
    Admins may orchestrate any application.
    """
    from app.agents.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(db=db)
    return orchestrator.run(application_id=application_id, triggered_by_user=current_user)


@router.get(
    "/orchestrate/{application_id}/status",
    response_model=OrchestrationRunResponse,
    tags=["Agent Orchestration"],
)
def get_orchestration_status_endpoint(
    application_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve latest orchestration run status for an application.
    Enforces applicant ownership and administrator authorization.
    """
    from app.agents.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(db=db)
    return orchestrator.get_latest_run_for_application(
        application_id=application_id,
        current_user=current_user,
    )


@router.get(
    "/orchestrate/runs/{run_id}",
    response_model=OrchestrationRunResponse,
    tags=["Agent Orchestration"],
)
def get_orchestration_run_endpoint(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve details of a specific orchestration run by runId.
    Enforces applicant ownership and administrator authorization.
    """
    from app.agents.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(db=db)
    return orchestrator.get_run(run_id=run_id, current_user=current_user)
