from datetime import datetime, timezone
import logging
import secrets
from typing import Any
from fastapi import HTTPException, status
import pymongo.errors
from pymongo.database import Database

from app.api.deps import assert_owner
from app.services.eligibility.engine import (
    EligibilityEvaluationResult,
    compute_input_hash,
    evaluate_eligibility,
)
from app.services.programme_rules import get_programme_rules

logger = logging.getLogger(__name__)


def run_eligibility_evaluation(
    db: Database,
    current_user: dict,
    application_id: str,
    run_id: str | None = None,
) -> EligibilityEvaluationResult:
    """
    Execute deterministic eligibility evaluation for an application and atomically persist result (D8).
    Allowed only when application is in ELIGIBILITY_CHECK status.
    Appends the evaluation snapshot to the append-only eligibility_evaluations collection.
    """
    app = db["applications"].find_one({"applicationId": application_id})
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{application_id}' not found.",
        )

    current_status = app.get("status")
    if current_status != "ELIGIBILITY_CHECK":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Eligibility evaluation is permitted only when application is in 'ELIGIBILITY_CHECK' status (current status: '{current_status}').",
        )

    programme_id = app.get("programmeId")
    if not programme_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Application '{application_id}' does not have a valid programmeId.",
        )

    rules = get_programme_rules(db, programme_id=programme_id)
    if not rules:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active programme rules found for programme '{programme_id}'.",
        )

    # Fetch all associated documents
    docs = list(db["documents"].find({"applicationId": application_id}))

    # Pure evaluation (D2-D7)
    evaluation_result = evaluate_eligibility(
        rules=rules,
        application_snapshot=app,
        documents_snapshot=docs,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    result_dict = evaluation_result.model_dump()

    # D8 Atomic Persistence on application with status guard
    atomic_filter: dict[str, Any] = {
        "applicationId": application_id,
        "status": "ELIGIBILITY_CHECK",
    }
    if run_id:
        # When a run_id is given, require activeRunId == run_id exactly
        atomic_filter["activeRunId"] = run_id

    # Append-only audit record structure (D8)
    user_id = str(current_user.get("_id") or current_user.get("id") or current_user.get("sub") or "orchestrator")
    eval_record = {
        "evaluationId": f"EVAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}",
        "applicationId": application_id,
        "userId": app.get("userId"),
        "programmeId": programme_id,
        "evaluatedBy": user_id,
        "evaluatorRole": current_user.get("role"),
        "runId": run_id,
        "evaluatedAt": now_iso,
        "status": evaluation_result.status,
        "inputHash": evaluation_result.inputHash,
        "ruleVersion": evaluation_result.ruleVersion,
        "evaluatorVersion": evaluation_result.evaluatorVersion,
        "summary": evaluation_result.summary,
        "result": result_dict,
    }

    # Atomic Persistence and Audit Consistency (D8):
    # When deployed on a MongoDB replica set, client session transactions write both the application
    # update and the audit record in eligibility_evaluations atomically.
    # On standalone MongoDB instances (e.g. single-node local development or test suites),
    # multi-document transactions raise ConfigurationError / OperationFailure. In that standalone
    # environment, the application update is executed first under strict status/runId guards, followed
    # by audit record insertion. We document this cross-collection atomicity gap for single-node deployments.
    persisted = False
    client = getattr(db, "client", None)
    if client and hasattr(client, "start_session"):
        try:
            with client.start_session() as session:
                with session.start_transaction():
                    update_res = db["applications"].update_one(
                        atomic_filter,
                        {
                            "$set": {
                                "eligibilityResult": result_dict,
                                "updatedAt": now_iso,
                            }
                        },
                        session=session,
                    )
                    if update_res.matched_count == 0:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Failed to persist eligibility result: application status changed or concurrent modification occurred.",
                        )
                    db["eligibility_evaluations"].insert_one(eval_record, session=session)
                    persisted = True
        except (pymongo.errors.ConfigurationError, pymongo.errors.OperationFailure, AttributeError):
            persisted = False

    if not persisted:
        update_res = db["applications"].update_one(
            atomic_filter,
            {
                "$set": {
                    "eligibilityResult": result_dict,
                    "updatedAt": now_iso,
                }
            },
        )
        if update_res.matched_count == 0:
            logger.warning(
                "Atomic eligibility persistence failed for application %s (status changed or lease lost).",
                application_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Failed to persist eligibility result: application status changed or concurrent modification occurred.",
            )
        db["eligibility_evaluations"].insert_one(eval_record)

    logger.info(
        "Application %s eligibility evaluated: %s (inputHash: %s).",
        application_id,
        evaluation_result.status,
        evaluation_result.inputHash,
    )

    return evaluation_result


def get_application_eligibility_result(
    db: Database,
    current_user: dict,
    application_id: str,
) -> dict[str, Any]:
    """
    Retrieve persisted eligibility result for an application.
    Enforces applicant ownership by userId via assert_owner, or admin role.
    """
    app = db["applications"].find_one({"applicationId": application_id})
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{application_id}' not found.",
        )

    assert_owner(app, current_user)

    eligibility = app.get("eligibilityResult")
    if not eligibility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Eligibility has not been evaluated for application '{application_id}' yet.",
        )

    return eligibility
