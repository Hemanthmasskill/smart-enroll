from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, applications, auth, documents
from app.api.deps import RequireRole
from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    connect_to_mongo()
    yield
    close_mongo_connection()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "online",
        "project": settings.PROJECT_NAME,
        "message": "Smart Enroll backend is up and running.",
    }


@app.get("/api/v1/db-health", tags=["Health"])
async def db_health(db=Depends(get_db)):
    db.command("ping")
    return {"status": "Database connected successfully"}
