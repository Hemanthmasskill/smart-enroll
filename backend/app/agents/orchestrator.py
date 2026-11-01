from app.api.deps import assert_owner
"""
Smart Enroll — Autonomous Agent Orchestrator (Increment 15, Task 15.2)

Implements the bounded agentic orchestration lifecycle:
    OBSERVE -> PLAN -> ACT -> VERIFY -> RE-PLAN

Integrates strictly with internal registered tools in app.agents.tools without
exposing public tool execution endpoints. Enforces server-side authorization
boundaries, deterministic verification precedence, concurrency protection,
and structured audit logging.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any
import uuid

from bson import ObjectId
from fastapi import HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.agents.tools import (
    REQUIRED_DOCUMENT_TYPES,
    execute_tool,
    tool_record_audit_event,
)
from app.schemas.agent import (
    OrchestrationOutcome,
    OrchestrationRunResponse,
    OrchestrationRunStatus,
    OrchestrationStepRecord,
    ToolName,
    ToolStatus,
    WorkflowStage,
)

logger = logging.getLogger(__name__)

SYSTEM_ORCHESTRATOR_USER = {
    "_id": "system_orchestrator",
    "role": "system",
    "full_name": "Autonomous Agent Orchestrator",
}


def map_outcome_to_lifecycle_status(outcome: OrchestrationOutcome) -> OrchestrationRunStatus:
    """
    Map business workflow outcome to execution lifecycle status.
    - COMPLETED, WAITING_FOR_APPLICANT, MANUAL_REVIEW_REQUIRED, DEPENDENCY_PENDING:
      The loop executed normally and successfully reached a verified decision/waiting state.
      Lifecycle is COMPLETED.
    - FAILED:
      Execution failed (tool error, unhandled exception, iteration limit exceeded).
      Lifecycle is FAILED.
    - ALREADY_RUNNING:
      Duplicate trigger; run is RUNNING.
    """
    if outcome in (
        OrchestrationOutcome.COMPLETED,
        OrchestrationOutcome.WAITING_FOR_APPLICANT,
        OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
        OrchestrationOutcome.DEPENDENCY_PENDING,
    ):
        return OrchestrationRunStatus.COMPLETED
    elif outcome in (OrchestrationOutcome.FAILED, OrchestrationOutcome.TIMEOUT):
        return OrchestrationRunStatus.FAILED
    elif outcome == OrchestrationOutcome.ALREADY_RUNNING:
        return OrchestrationRunStatus.RUNNING
    return OrchestrationRunStatus.FAILED


class ApplicationObservation:
    """
    Structured snapshot of observed application and document states
    collected strictly for workflow decision-making without chain-of-thought logging.
    """

    def __init__(
        self,
        application_id: str,
        current_status: str,
        programme_id: str,
        applicant_id: str | None,
        user_id: str | None,
        applicant_name: str,
        is_document_complete: bool,
        missing_document_types: list[str],
        uploaded_documents: list[dict[str, Any]],
        unprocessed_documents: list[dict[str, Any]],
        failed_documents: list[dict[str, Any]],
        mismatched_documents: list[dict[str, Any]],
        manual_review_documents: list[dict[str, Any]],
        validated_documents: list[dict[str, Any]],
        eligibility_result: dict[str, Any] | None,
    ):
        self.application_id = application_id
        self.current_status = current_status
        self.programme_id = programme_id
        self.applicant_id = applicant_id
        self.user_id = user_id
        self.applicant_name = applicant_name
        self.is_document_complete = is_document_complete
        self.missing_document_types = missing_document_types
        self.uploaded_documents = uploaded_documents
        self.unprocessed_documents = unprocessed_documents
        self.failed_documents = failed_documents
        self.mismatched_documents = mismatched_documents
        self.manual_review_documents = manual_review_documents
        self.validated_documents = validated_documents
        self.eligibility_result = eligibility_result

    @property
    def required_documents(self) -> list[str]:
        return sorted(list(REQUIRED_DOCUMENT_TYPES))


class PlannedAction:
    """
    Representation of a single planned internal tool invocation.
    """

    def __init__(
        self,
        tool: ToolName,
        parameters: dict[str, Any],
        rationale: str,
        stage: WorkflowStage = WorkflowStage.ACT,
        is_terminal: bool = False,
        terminal_outcome: OrchestrationOutcome | None = None,
        planner: str = "DETERMINISTIC",
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ):
        self.tool = tool
        self.parameters = parameters
        self.rationale = rationale
        self.stage = stage
        self.is_terminal = is_terminal
        self.terminal_outcome = terminal_outcome
        self.planner = planner
        self.fallback_used = fallback_used
        self.fallback_reason = fallback_reason


class PlanningStrategy(ABC):
    """
    Strategy interface for selecting the next workflow action.
    Enables future pluggable model-backed (LLM) planners while ensuring
    deterministic, testable state progression without external network calls.
    """

    @abstractmethod
    def plan_next_action(
        self,
        observation: ApplicationObservation,
        iteration: int,
    ) -> tuple[PlannedAction | None, OrchestrationOutcome | None, str | None]:
        """
        Evaluate observation and return:
        - PlannedAction (or None if no action to execute)
        - Final OrchestrationOutcome (if workflow should terminate or halt)
        - Reason / summary string
        """
        pass


def compute_expected_action(
    observation: ApplicationObservation,
) -> tuple[PlannedAction | None, OrchestrationOutcome | None, str | None]:
    """
    Pure deterministic decision table for application workflow progression.
    Evaluates observation snapshot and returns:
    - PlannedAction (or None if no action to execute)
    - Final OrchestrationOutcome (if workflow should terminate or halt)
    - Reason / summary string
    """
    app_id = observation.application_id
    status = observation.current_status

    # 1. DRAFT state: cannot orchestrate an unsubmitted draft
    if status == "DRAFT":
        return (
            None,
            OrchestrationOutcome.WAITING_FOR_APPLICANT,
            "Application is in DRAFT status. Awaiting applicant submission.",
        )

    # 2. SUBMITTED state: verify documents or initiate processing
    if status == "SUBMITTED":
        if not observation.is_document_complete:
            missing_str = ", ".join(observation.missing_document_types)
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "WAITING_FOR_DOCUMENTS"},
                    rationale=f"Missing {len(observation.missing_document_types)} required document(s): {missing_str}.",
                    is_terminal=True,
                    terminal_outcome=OrchestrationOutcome.WAITING_FOR_APPLICANT,
                ),
                OrchestrationOutcome.WAITING_FOR_APPLICANT,
                f"Waiting for applicant to upload missing required documents: {missing_str}.",
            )
        else:
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "PROCESSING"},
                    rationale="Application submitted with required documents. Initiating automated processing workflow.",
                ),
                None,
                None,
            )

    # 3. PROCESSING or WAITING_FOR_DOCUMENTS: document collection and processing
    if status in ("PROCESSING", "WAITING_FOR_DOCUMENTS"):
        # Check for missing required documents
        if not observation.is_document_complete:
            missing_str = ", ".join(observation.missing_document_types)
            if status != "WAITING_FOR_DOCUMENTS":
                return (
                    PlannedAction(
                        tool=ToolName.UPDATE_APPLICATION_STATUS,
                        parameters={"application_id": app_id, "new_status": "WAITING_FOR_DOCUMENTS"},
                        rationale=f"Missing {len(observation.missing_document_types)} required document(s): {missing_str}.",
                        is_terminal=True,
                        terminal_outcome=OrchestrationOutcome.WAITING_FOR_APPLICANT,
                    ),
                    OrchestrationOutcome.WAITING_FOR_APPLICANT,
                    f"Waiting for applicant to upload missing required documents: {missing_str}.",
                )
            else:
                return (
                    None,
                    OrchestrationOutcome.WAITING_FOR_APPLICANT,
                    f"Application is waiting for applicant to upload missing documents: {missing_str}.",
                )

        # All 6 documents are present. If status was WAITING_FOR_DOCUMENTS, resume PROCESSING
        if status == "WAITING_FOR_DOCUMENTS":
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "PROCESSING"},
                    rationale="All 6 required documents uploaded. Resuming workflow processing.",
                ),
                None,
                None,
            )

        # Check if any documents need OCR processing
        if observation.unprocessed_documents:
            next_doc = observation.unprocessed_documents[0]
            doc_id = next_doc.get("documentId")
            doc_type = next_doc.get("documentType", "DOCUMENT")
            return (
                PlannedAction(
                    tool=ToolName.PROCESS_DOCUMENT,
                    parameters={"document_id": doc_id},
                    rationale=f"Executing OCR extraction and classification for document '{doc_type}' ({doc_id}).",
                ),
                None,
                None,
            )

        # Check if any document failed OCR
        if observation.failed_documents:
            failed_types = [d.get("documentType", "DOCUMENT") for d in observation.failed_documents]
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "EXCEPTION"},
                    rationale=f"Document OCR processing failed for {len(failed_types)} document(s): {', '.join(failed_types)}.",
                    is_terminal=True,
                    terminal_outcome=OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                ),
                OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                f"Document processing failed for: {', '.join(failed_types)}. Manual inspection required.",
            )

        # All uploaded documents are processed. Check validation results
        if observation.mismatched_documents or observation.manual_review_documents:
            discrepancy_count = len(observation.mismatched_documents) + len(observation.manual_review_documents)
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "EXCEPTION"},
                    rationale=f"Validation detected {discrepancy_count} document(s) with data conflicts or manual review flags.",
                    is_terminal=True,
                    terminal_outcome=OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                ),
                OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                "Document validation encountered data conflicts or manual review conditions. Routed to exception management.",
            )

        # All documents are validated! Transition to VERIFICATION_IN_PROGRESS
        return (
            PlannedAction(
                tool=ToolName.UPDATE_APPLICATION_STATUS,
                parameters={"application_id": app_id, "new_status": "VERIFICATION_IN_PROGRESS"},
                rationale="All 6 required documents validated successfully. Transitioning to verification.",
            ),
            None,
            None,
        )

    # 4. VERIFICATION_IN_PROGRESS: advance to ELIGIBILITY_CHECK
    if status == "VERIFICATION_IN_PROGRESS":
        return (
            PlannedAction(
                tool=ToolName.UPDATE_APPLICATION_STATUS,
                parameters={"application_id": app_id, "new_status": "ELIGIBILITY_CHECK"},
                rationale="Document verification completed. Transitioning to eligibility evaluation.",
            ),
            None,
            None,
        )

    # 5. ELIGIBILITY_CHECK: invoke check_eligibility or advance based on deterministic result (Increment 16)
    if status == "ELIGIBILITY_CHECK":
        if not observation.eligibility_result:
            return (
                PlannedAction(
                    tool=ToolName.CHECK_ELIGIBILITY,
                    parameters={"application_id": app_id},
                    rationale="Evaluating academic admission eligibility against canonical programme rules.",
                ),
                None,
                None,
            )
        elig_status = observation.eligibility_result.get("status")
        if elig_status == "ELIGIBLE":
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "ELIGIBLE"},
                    rationale="Academic eligibility verified. Advancing status to ELIGIBLE.",
                ),
                None,
                None,
            )
        elif elig_status == "INELIGIBLE":
            summary = observation.eligibility_result.get("summary") or "Ineligible based on academic criteria"
            reason = f"Application evaluated as INELIGIBLE ({summary}); requires administrative confirmation before final rejection."
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={
                        "application_id": app_id,
                        "new_status": "EXCEPTION",
                        "reason": reason,
                    },
                    rationale=reason,
                    is_terminal=True,
                    terminal_outcome=OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                ),
                OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                reason,
            )
        elif elig_status == "NEEDS_REVIEW":
            # NEEDS_REVIEW moves the application to EXCEPTION with outcome MANUAL_REVIEW_REQUIRED;
            # creating the exception record stays DEPENDENCY_PENDING (Increment 17).
            summary = observation.eligibility_result.get("summary") or "Academic criteria requires manual review"
            reason = f"Eligibility evaluation requires manual review ({summary}). Routed to exception management."
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={
                        "application_id": app_id,
                        "new_status": "EXCEPTION",
                        "reason": reason,
                    },
                    rationale=reason,
                    is_terminal=True,
                    terminal_outcome=OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                ),
                OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
                reason,
            )

    # 6. EXCEPTION state: requires manual administrative intervention
    if status == "EXCEPTION":
        return (
            None,
            OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
            "Application is currently in EXCEPTION state. Awaiting administrative review or exception resolution.",
        )

    # 7. ELIGIBLE state:
    if status == "ELIGIBLE":
        if observation.eligibility_result and observation.eligibility_result.get("status") == "ELIGIBLE":
            return (
                PlannedAction(
                    tool=ToolName.UPDATE_APPLICATION_STATUS,
                    parameters={"application_id": app_id, "new_status": "PROCESSING_COMPLETE"},
                    rationale="Eligibility determined as ELIGIBLE. Concluding workflow processing.",
                    is_terminal=True,
                    terminal_outcome=OrchestrationOutcome.COMPLETED,
                ),
                OrchestrationOutcome.COMPLETED,
                "Application processing concluded with status ELIGIBLE.",
            )
        else:
            return (
                None,
                OrchestrationOutcome.DEPENDENCY_PENDING,
                "Deterministic eligibility evaluation result pending from Increment 16.",
            )

    # 7b. INELIGIBLE state: route to EXCEPTION for administrative confirmation
    if status == "INELIGIBLE":
        summary = ""
        if observation.eligibility_result:
            summary = observation.eligibility_result.get("summary") or ""
        reason = f"Application evaluated as INELIGIBLE{' (' + summary + ')' if summary else ''}; requires administrative confirmation before final rejection."
        return (
            PlannedAction(
                tool=ToolName.UPDATE_APPLICATION_STATUS,
                parameters={
                    "application_id": app_id,
                    "new_status": "EXCEPTION",
                    "reason": reason,
                },
                rationale=reason,
                is_terminal=True,
                terminal_outcome=OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
            ),
            OrchestrationOutcome.MANUAL_REVIEW_REQUIRED,
            reason,
        )

    # 8. PROCESSING_COMPLETE: terminal state
    if status == "PROCESSING_COMPLETE":
        return (
            None,
            OrchestrationOutcome.COMPLETED,
            "Application processing has already reached completion.",
        )

    return (
        None,
        OrchestrationOutcome.FAILED,
        f"Unrecognized application status '{status}'.",
    )


class DeterministicPlanningStrategy(PlanningStrategy):
    """
    Deterministic rule-based planning strategy for Increment 15.
    Coordinates application lifecycle, document OCR, Layer 2 validation,
    and dependency boundaries (Increment 16 Eligibility Engine) without
    fabricating results or bypassing deterministic validation.
    """
    planner_name: str = "DETERMINISTIC"

    def plan_next_action(
        self,
        observation: ApplicationObservation,
        iteration: int,
    ) -> tuple[PlannedAction | None, OrchestrationOutcome | None, str | None]:
        return compute_expected_action(observation)


class HeartbeatRenewer:
    """
    Background thread that periodically refreshes the orchestration run's
    heartbeat and extends its lease expiration while a tool is actively executing.
    Guarantees that a long-running tool call does not lose execution ownership
    or get prematurely mistaken for an abandoned execution.
    """

    def __init__(
        self,
        db: Database,
        run_id: str,
        application_id: str,
        stale_timeout_seconds: int = 300,
        interval_seconds: float = 1.0,
    ):
        self.db = db
        self.run_id = run_id
        self.application_id = application_id
        self.stale_timeout_seconds = stale_timeout_seconds
        # Interval is at most 1/3 of the stale timeout, bounded between 0.1s and 5.0s
        self.interval_seconds = max(0.1, min(interval_seconds, max(0.2, stale_timeout_seconds / 3.0)))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(self.interval_seconds):
            try:
                now_utc = datetime.now(timezone.utc)
                lease_exp = (now_utc + timedelta(seconds=self.stale_timeout_seconds)).isoformat()
                res = self.db["orchestration_runs"].update_one(
                    {
                        "runId": self.run_id,
                        "status": OrchestrationRunStatus.RUNNING.value,
                        "applicationId": self.application_id,
                    },
                    {
                        "$set": {
                            "heartbeatAt": now_utc.isoformat(),
                            "leaseExpiresAt": lease_exp,
                        },
                        "$inc": {"leaseVersion": 1},
                    },
                )
                if res.matched_count == 0:
                    break
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


class AgentOrchestrator:
    """
    Autonomous agent orchestrator executing the bounded lifecycle:
    OBSERVE -> PLAN -> ACT -> VERIFY -> RE-PLAN
    """

    def __init__(
        self,
        db: Database,
        planning_strategy: PlanningStrategy | None = None,
        max_iterations: int = 15,
        stale_timeout_seconds: int = 300,
    ):
        self.db = db
        if planning_strategy is not None:
            self.strategy = planning_strategy
        else:
            from app.core.config import settings
            from app.agents.providers import get_llm_provider
            from app.agents.llm_planner import LLMPlanningStrategy

            provider = get_llm_provider()
            if provider is not None:
                self.strategy = LLMPlanningStrategy(
                    provider=provider,
                    fallback_strategy=DeterministicPlanningStrategy(),
                    fallback_enabled=settings.LLM_FALLBACK_TO_DETERMINISTIC,
                    db=db,
                )
            else:
                self.strategy = DeterministicPlanningStrategy()
        self.max_iterations = max_iterations
        self.stale_timeout_seconds = stale_timeout_seconds

    def _is_run_stale(self, run_doc: dict, now_utc: datetime) -> bool:
        """
        Evaluate whether a RUNNING run record has expired its lease or heartbeat.
        Prefers leaseExpiresAt, then heartbeatAt, then startedAt as fallback.
        """
        lease_expires = run_doc.get("leaseExpiresAt")
        if lease_expires:
            try:
                exp_dt = datetime.fromisoformat(lease_expires)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                return now_utc >= exp_dt
            except Exception:
                pass

        heartbeat = run_doc.get("heartbeatAt")
        if heartbeat:
            try:
                hb_dt = datetime.fromisoformat(heartbeat)
                if hb_dt.tzinfo is None:
                    hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                return (now_utc - hb_dt).total_seconds() >= self.stale_timeout_seconds
            except Exception:
                pass

        started = run_doc.get("startedAt")
        if started:
            try:
                st_dt = datetime.fromisoformat(started)
                if st_dt.tzinfo is None:
                    st_dt = st_dt.replace(tzinfo=timezone.utc)
                return (now_utc - st_dt).total_seconds() >= self.stale_timeout_seconds
            except Exception:
                pass

        return False

    def _claim_or_recover_run(
        self,
        application_id: str,
        user_id: str,
        role: str,
        initial_status: str,
    ) -> tuple[dict | None, OrchestrationRunResponse | None]:
        """
        Atomically claim a new RUNNING record for the application in MongoDB.
        If an existing RUNNING record exists:
        - If stale (lease/heartbeat expired), atomically recover it using CAS update to ABORTED.
        - Retry claiming at most once after recovery.
        - If active or CAS race lost, return safe ALREADY_RUNNING response.
        """
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()

        for attempt in range(2):
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            attempt_now = datetime.now(timezone.utc)
            lease_expires_at = (attempt_now + timedelta(seconds=self.stale_timeout_seconds)).isoformat()

            run_doc = {
                "runId": run_id,
                "applicationId": application_id,
                "status": OrchestrationRunStatus.RUNNING.value,
                "outcome": None,
                "triggeredBy": user_id,
                "triggeredRole": role,
                "currentApplicationStatus": initial_status,
                "startedAt": attempt_now.isoformat(),
                "heartbeatAt": attempt_now.isoformat(),
                "leaseExpiresAt": lease_expires_at,
                "progressVersion": 1,
                "leaseVersion": 1,
                "completedAt": None,
                "stepsCompleted": 0,
                "steps": [],
                "summary": "Orchestration in progress",
                "failureReason": None,
                "pendingDependency": None,
            }

            try:
                self.db["orchestration_runs"].insert_one(run_doc)
                self.db["applications"].update_one(
                    {"applicationId": application_id},
                    {"$set": {"activeRunId": run_id}},
                )
                return run_doc, None
            except DuplicateKeyError:
                existing = self.db["orchestration_runs"].find_one(
                    {
                        "applicationId": application_id,
                        "status": {
                            "$in": [
                                OrchestrationRunStatus.RUNNING.value,
                                OrchestrationRunStatus.RECOVERING.value,
                            ]
                        },
                    }
                )
                if not existing:
                    # Concurrently completed or recovered between insert attempt and find_one; retry once
                    continue

                is_stale = self._is_run_stale(existing, attempt_now)
                if not is_stale or attempt >= 1:
                    return None, OrchestrationRunResponse(
                        runId=existing.get("runId", "run-existing"),
                        applicationId=application_id,
                        status=OrchestrationRunStatus.RUNNING,
                        outcome=OrchestrationOutcome.ALREADY_RUNNING,
                        currentApplicationStatus=initial_status,
                        stepsCompleted=existing.get("stepsCompleted", 0),
                        summary=f"An active orchestration run is already in progress for application '{application_id}'.",
                        startedAt=existing.get("startedAt", now_iso),
                    )

                stale_run_id = existing["runId"]
                stale_status = existing.get("status")
                stale_heartbeat = existing.get("heartbeatAt")
                stale_lease_expires = existing.get("leaseExpiresAt")
                stale_lease_version = existing.get("leaseVersion")

                # SAFE RECOVERY ORDERING:
                # Step 1: Preventing the old execution from retaining or reacquiring ownership.
                # CAS compare-and-set verifies the run is still RUNNING or RECOVERING, heartbeat is unchanged,
                # and lease has not been extended by a concurrent heartbeat.
                recovery_fence_token = f"superseded-{stale_run_id}"
                cas_filter = {
                    "runId": stale_run_id,
                    "applicationId": application_id,
                }
                if stale_heartbeat is not None:
                    cas_filter["heartbeatAt"] = stale_heartbeat
                if stale_lease_expires is not None:
                    cas_filter["leaseExpiresAt"] = stale_lease_expires
                if stale_lease_version is not None:
                    cas_filter["leaseVersion"] = stale_lease_version

                if stale_status == OrchestrationRunStatus.RUNNING.value:
                    cas_filter["status"] = OrchestrationRunStatus.RUNNING.value
                    cas_update = {
                        "$set": {
                            "status": OrchestrationRunStatus.RECOVERING.value,
                            "recoveryToken": recovery_fence_token,
                            "recoveredBy": run_id,
                            "heartbeatAt": attempt_now.isoformat(),
                            "leaseExpiresAt": (attempt_now + timedelta(seconds=self.stale_timeout_seconds)).isoformat(),
                        },
                        "$inc": {"leaseVersion": 1},
                    }
                else:
                    # Take over crashed RECOVERING execution
                    cas_filter["status"] = OrchestrationRunStatus.RECOVERING.value
                    cas_update = {
                        "$set": {
                            "recoveredBy": run_id,
                            "recoveryToken": recovery_fence_token,
                            "heartbeatAt": attempt_now.isoformat(),
                            "leaseExpiresAt": (attempt_now + timedelta(seconds=self.stale_timeout_seconds)).isoformat(),
                        },
                        "$inc": {"leaseVersion": 1},
                    }

                cas_result = self.db["orchestration_runs"].update_one(cas_filter, cas_update)
                if cas_result.modified_count != 1:
                    logger.info(
                        "CAS recovery race lost or heartbeat renewed for run %s on application %s",
                        stale_run_id,
                        application_id,
                    )
                    return None, OrchestrationRunResponse(
                        runId=stale_run_id,
                        applicationId=application_id,
                        status=OrchestrationRunStatus.RUNNING,
                        outcome=OrchestrationOutcome.ALREADY_RUNNING,
                        currentApplicationStatus=initial_status,
                        stepsCompleted=existing.get("stepsCompleted", 0),
                        summary=f"An active orchestration run is already in progress for application '{application_id}'.",
                        startedAt=existing.get("startedAt", now_iso),
                    )

                # Step 2: Revoking or transferring affected resource fencing tokens.
                # Step 3: Ensuring stale-worker writes cannot succeed once ownership is revoked.
                #
                # SAFE OPERATION ORDER:
                # 1. Atomically stamp stale_run_id into supersededRunIds across all documents
                #    and the application record. Any stale worker claiming after this point
                #    will be rejected by claim_filter["supersededRunIds"] = {"$ne": run_id}.
                # 2. Revoke activeRunId on documents currently owned by stale_run_id (and on application).
                #    If a stale worker committed a claim immediately before step 1 above,
                #    this subsequent revocation catches it and replaces activeRunId with recovery_fence_token.
                # 3. Only after all resource fencing is complete, declare old run abandoned and allow replacement.
                #
                # A) Stamp supersededRunIds and revoke on applications:
                self.db["applications"].update_one(
                    {"applicationId": application_id},
                    {"$addToSet": {"supersededRunIds": stale_run_id}},
                )
                self.db["applications"].update_one(
                    {"applicationId": application_id, "activeRunId": stale_run_id},
                    {"$set": {"activeRunId": recovery_fence_token}},
                )
                # B) Document resource fencing:
                # 1. Atomically stamp stale_run_id into supersededRunIds across ALL documents for this application
                self.db["documents"].update_many(
                    {"applicationId": application_id},
                    {"$addToSet": {"supersededRunIds": stale_run_id}},
                )
                # 2. Revoke activeRunId on documents currently owned by stale_run_id.
                # If a document was in-flight (processingStatus == "PROCESSING"), reset it to "UPLOADED"
                # so the replacement run can recover and process the document.
                self.db["documents"].update_many(
                    {"applicationId": application_id, "activeRunId": stale_run_id, "processingStatus": "PROCESSING"},
                    {"$set": {"activeRunId": recovery_fence_token, "processingStatus": "UPLOADED"}},
                )
                self.db["documents"].update_many(
                    {"applicationId": application_id, "activeRunId": stale_run_id},
                    {"$set": {"activeRunId": recovery_fence_token}},
                )

                # Step 4: Declaring the old run abandoned.
                # Only AFTER resource fencing tokens are revoked, mark the old run ABORTED.
                self.db["orchestration_runs"].update_one(
                    {"runId": stale_run_id, "status": OrchestrationRunStatus.RECOVERING.value},
                    {
                        "$set": {
                            "status": OrchestrationRunStatus.ABORTED.value,
                            "outcome": OrchestrationOutcome.FAILED.value,
                            "failureReason": "Execution lease expired and was abandoned; safely recovered by subsequent request.",
                            "summary": "Stale abandoned run recovered.",
                            "completedAt": attempt_now.isoformat(),
                        }
                    },
                )
                logger.info(
                    "Recovered stale abandoned run %s and revoked all resource fencing tokens for application %s",
                    stale_run_id,
                    application_id,
                )

                # Step 5: Allowing the replacement run to begin.
                continue

        existing_active = self.db["orchestration_runs"].find_one(
            {
                "applicationId": application_id,
                "status": {
                    "$in": [
                        OrchestrationRunStatus.RUNNING.value,
                        OrchestrationRunStatus.RECOVERING.value,
                    ]
                },
            }
        )
        active_id = existing_active.get("runId", "run-existing") if existing_active else "run-existing"
        active_started = existing_active.get("startedAt", now_iso) if existing_active else now_iso
        active_steps = existing_active.get("stepsCompleted", 0) if existing_active else 0

        return None, OrchestrationRunResponse(
            runId=active_id,
            applicationId=application_id,
            status=OrchestrationRunStatus.RUNNING,
            outcome=OrchestrationOutcome.ALREADY_RUNNING,
            currentApplicationStatus=initial_status,
            stepsCompleted=active_steps,
            summary=f"An active orchestration run is already in progress for application '{application_id}'.",
            startedAt=active_started,
        )

    def observe(self, application_id: str) -> ApplicationObservation:
        """
        Inspect the authorized application's persisted state and document slots.
        """
        app = self.db["applications"].find_one({"applicationId": application_id})
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Application '{application_id}' not found.",
            )

        docs = list(self.db["documents"].find({"applicationId": application_id}))

        submitted_types = set()
        for d in docs:
            dtype = d.get("documentType")
            dstatus = d.get("status")
            has_file = bool(d.get("originalFileName") or d.get("fileName") or d.get("storedFileName"))
            if dtype and dstatus != "NOT_UPLOADED" and has_file:
                submitted_types.add(dtype)

        missing_types = [dt for dt in REQUIRED_DOCUMENT_TYPES if dt not in submitted_types]
        is_complete = len(missing_types) == 0

        uploaded_docs = [d for d in docs if d.get("documentType") in submitted_types]
        unprocessed_docs = [
            d for d in uploaded_docs
            if d.get("processingStatus") not in ("COMPLETED", "FAILED")
        ]
        failed_docs = [
            d for d in uploaded_docs
            if d.get("processingStatus") == "FAILED"
        ]
        mismatched_docs = [
            d for d in uploaded_docs
            if d.get("validationStatus") == "MISMATCH" or d.get("status") == "MISMATCH"
        ]
        manual_review_docs = [
            d for d in uploaded_docs
            if d.get("validationStatus") == "MANUAL_REVIEW" or d.get("status") == "MANUAL_REVIEW"
        ]
        validated_docs = [
            d for d in uploaded_docs
            if d.get("validationStatus") == "VALIDATED" and d.get("status") == "VALIDATED"
        ]

        applicant_name = app.get("fullName") or app.get("applicantName", "Applicant")

        return ApplicationObservation(
            application_id=application_id,
            current_status=app.get("status", "DRAFT"),
            programme_id=app.get("programmeId", ""),
            applicant_id=app.get("applicantId"),
            user_id=app.get("userId"),
            applicant_name=applicant_name,
            is_document_complete=is_complete,
            missing_document_types=missing_types,
            uploaded_documents=uploaded_docs,
            unprocessed_documents=unprocessed_docs,
            failed_documents=failed_docs,
            mismatched_documents=mismatched_docs,
            manual_review_documents=manual_review_docs,
            validated_documents=validated_docs,
            eligibility_result=app.get("eligibilityResult"),
        )

    def run(
        self,
        application_id: str,
        triggered_by_user: dict,
        max_iterations: int | None = None,
    ) -> OrchestrationRunResponse:
        """
        Execute the bounded orchestration loop for the specified application.
        Enforces:
        - RBAC: Applicant may only orchestrate their own application; Admin can orchestrate any application.
        - Persistence-backed atomic concurrency claim and safe stale-run lease recovery.
        - Loop bounds (max_iterations) and execution ownership fencing.
        - Safe audit logging without private chain-of-thought.
        """
        limit = max_iterations if max_iterations is not None else self.max_iterations

        # 1. Authorization check
        app = self.db["applications"].find_one({"applicationId": application_id})
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Application '{application_id}' not found.",
            )

        role = triggered_by_user.get("role")
        user_id = str(triggered_by_user.get("_id") or triggered_by_user.get("id"))
        if role == "applicant":
            assert_owner(app, triggered_by_user)
        elif role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this role.",
            )

        # 2. Concurrency claim and stale lease recovery
        run_doc, early_response = self._claim_or_recover_run(
            application_id=application_id,
            user_id=user_id,
            role=role,
            initial_status=app.get("status", "DRAFT"),
        )
        if early_response is not None:
            return early_response

        run_id = run_doc["runId"]
        now_iso = run_doc["startedAt"]

        # 3. Resolve user contexts
        app_user_id = app.get("userId")
        owner_user = None
        if app_user_id:
            try:
                owner_user = self.db["users"].find_one({"_id": ObjectId(app_user_id)})
            except Exception:
                owner_user = self.db["users"].find_one({"_id": app_user_id})

        if not owner_user:
            owner_user = {
                "_id": app_user_id or user_id,
                "role": "applicant",
                "applicant_id": app.get("applicantId"),
                "full_name": app.get("fullName", "Applicant"),
            }

        system_context = SYSTEM_ORCHESTRATOR_USER

        is_fenced = False
        steps: list[OrchestrationStepRecord] = []
        final_outcome = OrchestrationOutcome.FAILED
        summary = ""
        failure_reason = None
        pending_dependency = None
        fallback_occurred = False
        fallback_count = 0
        start_time = time.monotonic()

        try:
            for iteration in range(1, limit + 1):
                # Timeout Check
                from app.core.config import settings
                elapsed = time.monotonic() - start_time
                if elapsed > settings.ORCHESTRATION_MAX_SECONDS:
                    logger.warning(
                        "Orchestration run %s for application %s exceeded maximum execution time (%s > %s). Aborting with TIMEOUT.",
                        run_id,
                        application_id,
                        elapsed,
                        settings.ORCHESTRATION_MAX_SECONDS,
                    )
                    final_outcome = OrchestrationOutcome.TIMEOUT
                    failure_reason = f"Execution exceeded maximum wall-clock timeout of {settings.ORCHESTRATION_MAX_SECONDS} seconds."
                    summary = failure_reason
                    tool_record_audit_event(
                        db=self.db,
                        current_user=system_context,
                        application_id=application_id,
                        stage=WorkflowStage.RE_PLAN.value,
                        tool="orchestrator",
                        action="Orchestration run timed out",
                        result=failure_reason,
                        status="FAILED",
                        applicant_name=owner_user.get("full_name", "Applicant"),
                    )
                    break

                # Fencing & Heartbeat Check
                now_step = datetime.now(timezone.utc)
                lease_expires_step = (now_step + timedelta(seconds=self.stale_timeout_seconds)).isoformat()

                fence_result = self.db["orchestration_runs"].update_one(
                    {
                        "runId": run_id,
                        "status": OrchestrationRunStatus.RUNNING.value,
                        "applicationId": application_id,
                    },
                    {
                        "$set": {
                            "heartbeatAt": now_step.isoformat(),
                            "leaseExpiresAt": lease_expires_step,
                        },
                        "$inc": {"progressVersion": 1, "leaseVersion": 1},
                    },
                )
                if fence_result.matched_count == 0:
                    logger.warning(
                        "Execution ownership lost for run %s on application %s; fencing triggered. Halting without further tool calls.",
                        run_id,
                        application_id,
                    )
                    is_fenced = True
                    final_outcome = OrchestrationOutcome.FAILED
                    failure_reason = "Execution lease superseded or aborted by external recovery."
                    summary = "Execution ownership was lost or superseded; workflow halted safely."
                    break

                # OBSERVE
                observation = self.observe(application_id)

                tool_record_audit_event(
                    db=self.db,
                    current_user=system_context,
                    application_id=application_id,
                    stage=WorkflowStage.OBSERVE.value,
                    tool="get_application",
                    action=f"Observed application status '{observation.current_status}'",
                    result=f"Documents submitted: {len(observation.uploaded_documents)}/6",
                    status="COMPLETED",
                    applicant_name=observation.applicant_name,
                )

                # PLAN
                planned_action, early_outcome, plan_summary = self.strategy.plan_next_action(
                    observation=observation,
                    iteration=iteration,
                )

                is_iteration_fallback = bool(
                    getattr(planned_action, "fallback_used", False)
                    or getattr(self.strategy, "last_iteration_fallback", False)
                )
                if is_iteration_fallback:
                    fallback_occurred = True
                    fallback_count += 1

                if early_outcome:
                    final_outcome = early_outcome
                    summary = plan_summary or f"Workflow halted with outcome: {early_outcome.value}"
                    if not planned_action:
                        break

                if not planned_action:
                    if early_outcome:
                        final_outcome = early_outcome
                        summary = plan_summary or f"Workflow halted with outcome: {early_outcome.value}"
                    else:
                        if observation.current_status == "PROCESSING_COMPLETE":
                            final_outcome = OrchestrationOutcome.COMPLETED
                            summary = plan_summary or "Application processing is complete."
                        elif observation.current_status in ("DRAFT", "WAITING_FOR_DOCUMENTS"):
                            final_outcome = OrchestrationOutcome.WAITING_FOR_APPLICANT
                            summary = plan_summary or f"Awaiting applicant action in status '{observation.current_status}'."
                        elif observation.current_status == "EXCEPTION":
                            final_outcome = OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
                            summary = plan_summary or "Application is in EXCEPTION status requiring manual review."
                        elif observation.current_status == "ELIGIBILITY_CHECK":
                            final_outcome = OrchestrationOutcome.DEPENDENCY_PENDING
                            summary = plan_summary or "Application is awaiting Increment 16 eligibility engine."
                        else:
                            final_outcome = OrchestrationOutcome.FAILED
                            summary = plan_summary or f"Workflow halted unexpectedly in unfinished state '{observation.current_status}' without planned action."
                    break

                # ACT - Enforce fencing check immediately before executing any state-changing tool call
                now_act = datetime.now(timezone.utc)
                lease_expires_act = (now_act + timedelta(seconds=self.stale_timeout_seconds)).isoformat()
                act_fence = self.db["orchestration_runs"].update_one(
                    {
                        "runId": run_id,
                        "status": OrchestrationRunStatus.RUNNING.value,
                        "applicationId": application_id,
                    },
                    {
                        "$set": {
                            "heartbeatAt": now_act.isoformat(),
                            "leaseExpiresAt": lease_expires_act,
                        },
                        "$inc": {"leaseVersion": 1},
                    },
                )
                if act_fence.matched_count == 0:
                    logger.warning(
                        "Execution ownership lost for run %s on application %s immediately before ACT; fencing triggered. Halting.",
                        run_id,
                        application_id,
                    )
                    is_fenced = True
                    final_outcome = OrchestrationOutcome.FAILED
                    failure_reason = "Execution lease superseded or aborted by external recovery."
                    summary = "Execution ownership was lost or superseded; workflow halted safely."
                    break

                if planned_action.tool == ToolName.UPDATE_APPLICATION_STATUS:
                    exec_context = system_context
                else:
                    exec_context = owner_user

                renewer = HeartbeatRenewer(
                    db=self.db,
                    run_id=run_id,
                    application_id=application_id,
                    stale_timeout_seconds=self.stale_timeout_seconds,
                )
                renewer.start()
                try:
                    tool_result = execute_tool(
                        tool_name=planned_action.tool.value,
                        parameters=planned_action.parameters,
                        current_user=exec_context,
                        db=self.db,
                        run_id=run_id,
                    )
                finally:
                    renewer.stop()

                if tool_result.status == ToolStatus.FAILED.value and "ownership" in (tool_result.message or "").lower():
                    logger.warning(
                        "Tool execution failed due to ownership loss/fencing for run %s",
                        run_id,
                    )
                    is_fenced = True
                    final_outcome = OrchestrationOutcome.FAILED
                    failure_reason = tool_result.message
                    summary = "Execution ownership was lost or superseded; workflow halted safely."
                    break

                # VERIFY
                is_step_fallback = bool(getattr(planned_action, "fallback_used", False))
                step_record = OrchestrationStepRecord(
                    stepIndex=iteration,
                    stage=planned_action.stage.value,
                    tool=planned_action.tool.value,
                    action=planned_action.rationale,
                    resultSummary=tool_result.message or tool_result.status,
                    status=tool_result.status,
                    executedAt=datetime.now(timezone.utc).isoformat(),
                    planner="FALLBACK" if is_step_fallback else getattr(planned_action, "planner", getattr(self.strategy, "planner_name", "DETERMINISTIC")),
                    fallbackUsed=is_step_fallback,
                    fallbackReason=getattr(planned_action, "fallback_reason", None),
                )
                steps.append(step_record)

                tool_record_audit_event(
                    db=self.db,
                    current_user=system_context,
                    application_id=application_id,
                    stage=planned_action.stage.value,
                    tool=planned_action.tool.value,
                    action=planned_action.rationale,
                    result=tool_result.message or tool_result.status,
                    status=tool_result.status,
                    applicant_name=observation.applicant_name,
                )

                # RE-PLAN / Outcome verification
                if tool_result.status == ToolStatus.DEPENDENCY_PENDING.value:
                    final_outcome = OrchestrationOutcome.DEPENDENCY_PENDING
                    pending_dependency = tool_result.dependency or "Pending external increment service"
                    summary = tool_result.message or f"Dependency pending: {pending_dependency}"
                    break

                if tool_result.status == ToolStatus.FAILED.value:
                    final_outcome = OrchestrationOutcome.FAILED
                    failure_reason = tool_result.message
                    summary = f"Tool '{planned_action.tool.value}' execution failed: {tool_result.message}"
                    break

                if planned_action.is_terminal and planned_action.terminal_outcome:
                    final_outcome = planned_action.terminal_outcome
                    summary = plan_summary or f"Terminal workflow action completed with outcome: {final_outcome.value}"
                    break

            else:
                # Reached bounded iteration limit
                final_outcome = OrchestrationOutcome.FAILED
                failure_reason = f"Execution exceeded maximum bounded iteration limit of {limit} steps."
                summary = failure_reason

        except Exception as exc:
            logger.exception(
                "Unexpected error in orchestration loop for application %s: %s",
                application_id,
                str(exc),
            )
            final_outcome = OrchestrationOutcome.FAILED
            failure_reason = "An unexpected internal error occurred during workflow execution."
            summary = "Workflow halted due to an unexpected execution error."
        finally:
            completed_iso = datetime.now(timezone.utc).isoformat()
            final_app = self.db["applications"].find_one({"applicationId": application_id})
            final_status = final_app.get("status", "DRAFT") if final_app else "UNKNOWN"
            lifecycle_status = map_outcome_to_lifecycle_status(final_outcome)

            if not is_fenced:
                self.db["applications"].update_one(
                    {"applicationId": application_id, "activeRunId": run_id},
                    {"$unset": {"activeRunId": ""}},
                )
                self.db["orchestration_runs"].update_one(
                    {"runId": run_id, "status": OrchestrationRunStatus.RUNNING.value},
                    {
                        "$set": {
                            "status": lifecycle_status.value,
                            "outcome": final_outcome.value,
                            "currentApplicationStatus": final_status,
                            "stepsCompleted": len(steps),
                            "steps": [s.model_dump() for s in steps],
                            "summary": summary,
                            "failureReason": failure_reason,
                            "pendingDependency": pending_dependency,
                            "completedAt": completed_iso,
                            "fallbackOccurred": fallback_occurred,
                            "fallbackCount": fallback_count,
                        }
                    },
                )

        return OrchestrationRunResponse(
            runId=run_id,
            applicationId=application_id,
            status=OrchestrationRunStatus.ABORTED if is_fenced else lifecycle_status,
            outcome=final_outcome,
            currentApplicationStatus=final_status,
            stepsCompleted=len(steps),
            summary=summary,
            failureReason=failure_reason,
            pendingDependency=pending_dependency,
            startedAt=now_iso,
            completedAt=completed_iso,
            steps=steps,
            planner=getattr(self.strategy, "planner_name", "DETERMINISTIC"),
            fallbackOccurred=fallback_occurred,
            fallbackCount=fallback_count,
        )

    def get_run(self, run_id: str, current_user: dict) -> OrchestrationRunResponse:
        """Retrieve a specific orchestration run by runId with authorization enforcement."""
        run_doc = self.db["orchestration_runs"].find_one({"runId": run_id}, {"_id": 0})
        if not run_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Orchestration run '{run_id}' not found.",
            )

        app_id = run_doc.get("applicationId")
        if current_user.get("role") == "applicant":
            app = self.db["applications"].find_one({"applicationId": app_id})
            if not app:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this orchestration run.",
                )
            assert_owner(app, current_user)

        return OrchestrationRunResponse.model_validate(run_doc)

    def get_latest_run_for_application(
        self,
        application_id: str,
        current_user: dict,
    ) -> OrchestrationRunResponse:
        """Retrieve the latest orchestration run for an application with authorization enforcement."""
        if current_user.get("role") == "applicant":
            app = self.db["applications"].find_one({"applicationId": application_id})
            if not app:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access orchestration for this application.",
                )
            assert_owner(app, current_user)

        run_doc = self.db["orchestration_runs"].find_one(
            {"applicationId": application_id},
            sort=[("startedAt", -1)],
            projection={"_id": 0},
        )
        if not run_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No orchestration runs found for application '{application_id}'.",
            )

        return OrchestrationRunResponse.model_validate(run_doc)
