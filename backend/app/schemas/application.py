from pydantic import BaseModel


class ApplicationResponse(BaseModel):
    applicationId: str
    applicantId: str
    programmeId: str
    status: str
    progressPercent: int
    documentsSubmitted: int
    documentsRequired: int
    eligibilityStatus: str
    unreadNotifications: int
    nextAction: str
    currentAction: str
    submittedAt: str
