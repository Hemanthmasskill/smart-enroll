from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.schemas.application import ApplicationResponse
from app.services.application import create_application, get_application
from app.utils.seed_data import MOCK_APPLICATION

router = APIRouter()


@router.post("/seed")
def seed_application(db=Depends(get_db)):
    create_application(db, MOCK_APPLICATION)
    return {"status": "Database seeded successfully"}


@router.get("/{applicant_id}", response_model=ApplicationResponse)
def get_application_by_id(applicant_id: str, db=Depends(get_db)):
    application = get_application(db, applicant_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application
