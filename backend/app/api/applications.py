from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app.api.deps import RequireRole, get_current_user
from app.core.database import get_db
from app.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationSummaryResponse,
    ApplicationUpdate,
)
from app.services.application import (
    create_application,
    get_application_by_id,
    get_application_for_user,
    list_applications,
    seed_application_record,
    submit_application,
    update_application,
)
from app.utils.seed_data import MOCK_APPLICATION

router = APIRouter()


@router.post("/seed", tags=["Applications"])
def seed_application(db: Database = Depends(get_db)):
    """
    Seed mock application data for development and testing.
    Idempotent operation.
    """
    seed_application_record(db, MOCK_APPLICATION)
    return {"status": "Database seeded successfully"}


@router.get("/me", response_model=ApplicationResponse, tags=["Applications"])
def get_current_applicant_application(
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Retrieve the application belonging to the authenticated applicant.
    Returns 404 if the applicant has not created an application yet.
    """
    return get_application_for_user(db, current_user)


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Applications"],
)
def create_new_application(
    app_in: ApplicationCreate,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Create a new application in DRAFT state for the authenticated applicant.
    Enforces single application per applicant (409 Conflict on duplicate).
    """
    return create_application(db, current_user, app_in)


@router.get(
    "",
    response_model=list[ApplicationSummaryResponse],
    tags=["Applications"],
)
def list_all_applications(
    current_user: dict = Depends(RequireRole(["admin"])),
    db: Database = Depends(get_db),
):
    """
    Admin-only endpoint: list application summaries.
    """
    return list_applications(db)


@router.get(
    "/{application_id}",
    response_model=ApplicationResponse,
    tags=["Applications"],
)
def get_application(
    application_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve an application by applicationId or applicantId.
    Admin can retrieve any application.
    Applicant can retrieve ONLY their own application.
    """
    return get_application_by_id(db, current_user, application_id)


@router.put(
    "/{application_id}",
    response_model=ApplicationResponse,
    tags=["Applications"],
)
def update_draft_application(
    application_id: str,
    app_update: ApplicationUpdate,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Update editable fields of an application.
    Allowed only for the application owner and only while in DRAFT status.
    """
    return update_application(db, current_user, application_id, app_update)


@router.post(
    "/{application_id}/submit",
    response_model=ApplicationResponse,
    tags=["Applications"],
)
def submit_draft_application(
    application_id: str,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Submit a draft application.
    Validates completeness and programme selection, then transitions status to SUBMITTED.
    """
    return submit_application(db, current_user, application_id)
