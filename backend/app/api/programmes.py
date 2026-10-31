from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.database import Database

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.programme import ProgrammeRulesResponse
from app.services.programme_rules import get_programme_rules

router = APIRouter()


@router.get(
    "/{programmeId}/rules",
    response_model=ProgrammeRulesResponse,
    summary="Get programme admission and eligibility rules",
)
def get_rules_for_programme(
    programmeId: str,
    version: str | None = Query(None, description="Optional rule version (defaults to latest)"),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> Any:
    """
    Retrieve configured deterministic admission requirements and academic thresholds for a programme.
    Accessible to any authenticated user.
    """
    rule = get_programme_rules(db, programme_id=programmeId, version=version)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Programme rules for '{programmeId}' not found.",
        )
    return rule
