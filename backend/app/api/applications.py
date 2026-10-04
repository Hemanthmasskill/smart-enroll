from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()

MOCK_APPLICATION = {
    "applicationId": "SE20260001",
    "applicantId": "APL-1001",
    "programmeId": "mca",
    "status": "WAITING_FOR_DOCUMENTS",
    "progressPercent": 45,
    "documentsSubmitted": 4,
    "documentsRequired": 6,
    "eligibilityStatus": "PENDING",
    "unreadNotifications": 3,
    "nextAction": "2 documents are still required.",
    "currentAction": "Smart Enroll is verifying your submitted documents and waiting for the remaining required files.",
    "submittedAt": "2026-09-05",
}


@router.get("/{applicant_id}")
async def get_application(applicant_id: str):
    if applicant_id == "APL-1001":
        return MOCK_APPLICATION
    raise HTTPException(status_code=404, detail="Application not found")
