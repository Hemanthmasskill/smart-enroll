from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, applications, auth, documents
from app.api.deps import RequireRole
from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_db
from app.core.logging_config import RequestIdMiddleware, SensitiveDataRedactionFilter
from app.core.rate_limit import enforce_rate_limit, get_client_ip
from app.core.security import validate_secret_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_secret_key()
    connect_to_mongo()
    yield
    from app.agents.providers import close_llm_provider
    close_llm_provider()
    close_mongo_connection()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Attach Redaction Filter to root and app loggers
for handler in logging.root.handlers:
    handler.addFilter(SensitiveDataRedactionFilter())

app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    auth.router,
    prefix=f"{settings.API_V1_STR}/auth",
    tags=["Authentication"],
)

app.include_router(
    applications.router,
    prefix=f"{settings.API_V1_STR}/applications",
    tags=["Applications"],
)

app.include_router(
    documents.router,
    prefix=f"{settings.API_V1_STR}/documents",
    tags=["Documents"],
)

app.include_router(
    agents.router,
    prefix=f"{settings.API_V1_STR}/agents",
    tags=["Agent Orchestration"],
)

# Admin alias for direct frontend compatibility: GET /api/v1/admin/agent-activity
@app.get(
    f"{settings.API_V1_STR}/admin/agent-activity",
    response_model=list[agents.AuditEventRecord],
    tags=["Agent Orchestration"],
)
def admin_agent_activity_alias(
    applicationId: str | None = None,
    stage: str | None = None,
    status: str | None = None,
    limit: int = 100,
    current_user: dict = Depends(RequireRole(["admin"])),
    db=Depends(get_db),
):
    return agents.list_agent_activity(
        db=db,
        current_user=current_user,
        application_id=applicationId,
        stage=stage,
        status=status,
        limit=limit,
    )


@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
async def health_check():
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "message": "Smart Enroll backend is up and running.",
    }


@app.get("/api/v1/db-health", tags=["Health"])
async def db_health(request: Request, db=Depends(get_db)):
    ip = get_client_ip(request)
    enforce_rate_limit(f"db_health:{ip}", max_requests=30, window_seconds=60, action_description="health check requests")
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception as exc:
        logging.getLogger(__name__).error(f"Database health check failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable",
        )
