"""
Smart Enroll — Model-Backed Planning Strategy (Increment 15, Task 15.3)

Implements LLMPlanningStrategy through the existing PlanningStrategy interface.
Features:
- Structured planning prompts using minimal, sanitized observations (zero PII transmitted).
- Strict output validation against LLMPlanProposal schema.
- Comprehensive security guardrails: LLM cannot bypass verification, cannot decide
  eligibility, cannot execute arbitrary code, and cannot make direct database updates.
- Robust deterministic fallback when provider fails, times out, rate limits,
  or returns malformed/out-of-policy responses.
- Structured audit logging of fallback events in agent_activity without credential leakage.
"""

import json
import logging
import re
from typing import Any

from pymongo.database import Database

from app.agents.orchestrator import (
    ApplicationObservation,
    DeterministicPlanningStrategy,
    PlannedAction,
    PlanningStrategy,
    compute_expected_action,
)
from app.agents.providers import (
    LLMProvider,
    LLMProviderConnectionError,
    LLMProviderError,
    LLMProviderHTTPError,
    LLMProviderTimeoutError,
)
from app.agents.tools import (
    TOOL_REGISTRY,
    tool_record_audit_event,
)
from app.schemas.agent import (
    ALLOWED_APPLICATION_STATUSES,
    LLMPlanProposal,
    OrchestrationOutcome,
    ToolName,
    WorkflowStage,
)

logger = logging.getLogger(__name__)

TOOL_PARAM_SCHEMAS: dict[str, dict[str, type | tuple[type, ...]]] = {
    ToolName.GET_APPLICATION.value: {
        "application_id": str,
    },
    ToolName.GET_PROGRAM_REQUIREMENTS.value: {
        "programme_id": str,
    },
    ToolName.CHECK_DOCUMENT_COMPLETENESS.value: {
        "application_id": str,
    },
    ToolName.PROCESS_DOCUMENT.value: {
        "document_id": str,
    },
    ToolName.EXTRACT_DOCUMENT_DATA.value: {
        "document_id": str,
    },
    ToolName.VERIFY_DOCUMENT.value: {
        "document_id": str,
    },
    ToolName.COMPARE_APPLICANT_DETAILS.value: {
        "document_id": str,
        "application_id": str,
    },
    ToolName.CHECK_ELIGIBILITY.value: {
        "application_id": str,
    },
    ToolName.CREATE_EXCEPTION.value: {
        "application_id": str,
        "exception_type": str,
        "description": str,
        "severity": str,
    },
    ToolName.REQUEST_MISSING_DOCUMENT.value: {
        "application_id": str,
        "document_type": str,
    },
    ToolName.UPDATE_APPLICATION_STATUS.value: {
        "application_id": str,
        "new_status": str,
        "reason": str,
    },
    ToolName.SEND_NOTIFICATION.value: {
        "title": str,
        "description": str,
        "user_id": str,
        "applicant_id": str,
    },
}

FORBIDDEN_PARAM_KEYS = {"run_id", "db", "current_user", "credentials", "token"}

ALLOWED_TOOLS_BY_STATUS = {
    "DRAFT": set(),
    "SUBMITTED": {
        ToolName.UPDATE_APPLICATION_STATUS.value,
        ToolName.CHECK_DOCUMENT_COMPLETENESS.value,
        ToolName.GET_APPLICATION.value,
    },
    "WAITING_FOR_DOCUMENTS": {
        ToolName.UPDATE_APPLICATION_STATUS.value,
        ToolName.REQUEST_MISSING_DOCUMENT.value,
        ToolName.CHECK_DOCUMENT_COMPLETENESS.value,
        ToolName.GET_APPLICATION.value,
    },
    "PROCESSING": {
        ToolName.PROCESS_DOCUMENT.value,
        ToolName.EXTRACT_DOCUMENT_DATA.value,
        ToolName.VERIFY_DOCUMENT.value,
        ToolName.COMPARE_APPLICANT_DETAILS.value,
        ToolName.CHECK_DOCUMENT_COMPLETENESS.value,
        ToolName.GET_APPLICATION.value,
        ToolName.UPDATE_APPLICATION_STATUS.value,
        ToolName.CREATE_EXCEPTION.value,
    },
    "VERIFICATION_IN_PROGRESS": {
        ToolName.UPDATE_APPLICATION_STATUS.value,
        ToolName.GET_APPLICATION.value,
    },
    "ELIGIBILITY_CHECK": {
        ToolName.CHECK_ELIGIBILITY.value,
        ToolName.GET_APPLICATION.value,
        ToolName.GET_PROGRAM_REQUIREMENTS.value,
        ToolName.UPDATE_APPLICATION_STATUS.value,
    },
    "EXCEPTION": {
        ToolName.CREATE_EXCEPTION.value,
        ToolName.GET_APPLICATION.value,
        ToolName.SEND_NOTIFICATION.value,
    },
    "ELIGIBLE": {
        ToolName.UPDATE_APPLICATION_STATUS.value,
        ToolName.SEND_NOTIFICATION.value,
    },
    "INELIGIBLE": {
        ToolName.UPDATE_APPLICATION_STATUS.value,
        ToolName.SEND_NOTIFICATION.value,
    },
    "PROCESSING_COMPLETE": set(),
}

ALLOWED_TERMINAL_OUTCOMES_BY_STATUS = {
    "DRAFT": {OrchestrationOutcome.WAITING_FOR_APPLICANT},
    "SUBMITTED": {OrchestrationOutcome.WAITING_FOR_APPLICANT},
    "WAITING_FOR_DOCUMENTS": {OrchestrationOutcome.WAITING_FOR_APPLICANT},
    "PROCESSING": {OrchestrationOutcome.MANUAL_REVIEW_REQUIRED, OrchestrationOutcome.WAITING_FOR_APPLICANT},
    "VERIFICATION_IN_PROGRESS": set(),
    "ELIGIBILITY_CHECK": {OrchestrationOutcome.DEPENDENCY_PENDING, OrchestrationOutcome.MANUAL_REVIEW_REQUIRED},
    "EXCEPTION": {OrchestrationOutcome.MANUAL_REVIEW_REQUIRED},
    "ELIGIBLE": {OrchestrationOutcome.COMPLETED, OrchestrationOutcome.DEPENDENCY_PENDING},
    "INELIGIBLE": {OrchestrationOutcome.MANUAL_REVIEW_REQUIRED, OrchestrationOutcome.DEPENDENCY_PENDING},
    "PROCESSING_COMPLETE": {OrchestrationOutcome.COMPLETED},
}


def _check_string_for_path_traversal(val: str, key_name: str) -> None:
    if any(seq in val for seq in ("..", "/", "\\", "\x00")):
        raise ValueError(
            f"Path traversal or restricted character sequence detected in parameter '{key_name}'."
        )


# =====================================================================
# Observation Sanitizer (Strict Privacy)
# =====================================================================

def sanitize_observation_for_llm(observation: ApplicationObservation) -> dict[str, Any]:
    """
    Produce a minimal, privacy-preserving observation dictionary for the LLM.
    Strictly excludes:
    - Applicant full name
    - Applicant ID and user ID
    - Contact information (email, phone, address)
    - Raw OCR text and document file contents
    - Marks, percentages, and registration numbers
    Includes only operational workflow tokens: application status, programme ID,
    document completeness, and document slot lifecycle states.
    """
    docs_summary = []
    for d in observation.uploaded_documents:
        docs_summary.append({
            "documentId": d.get("documentId"),
            "documentType": d.get("documentType"),
            "processingStatus": d.get("processingStatus"),
            "validationStatus": d.get("validationStatus"),
            "status": d.get("status"),
        })

    return {
        "applicationId": observation.application_id,
        "currentStatus": observation.current_status,
        "programmeId": observation.programme_id,
        "isDocumentComplete": observation.is_document_complete,
        "missingDocumentTypes": list(observation.missing_document_types),
        "uploadedDocumentsCount": len(observation.uploaded_documents),
        "unprocessedDocumentsCount": len(observation.unprocessed_documents),
        "failedDocumentsCount": len(observation.failed_documents),
        "mismatchedDocumentsCount": len(observation.mismatched_documents),
        "manualReviewDocumentsCount": len(observation.manual_review_documents),
        "validatedDocumentsCount": len(observation.validated_documents),
        "hasEligibilityResult": bool(observation.eligibility_result),
        "documents": docs_summary,
    }


# =====================================================================
# Prompt Templates
# =====================================================================

SYSTEM_PLANNING_PROMPT = """You are the autonomous admission workflow planner for Smart Enroll.
Your role is to inspect the current application workflow state and propose the single next appropriate action.
You must return ONLY a single valid JSON object adhering strictly to the planning schema.

CRITICAL WORKFLOW INVARIANTS & STATE-PRIORITY RULES (MUST FOLLOW IN ORDER):
1. DRAFT Application State:
   - If currentStatus is 'DRAFT': The application has NOT been submitted by the applicant.
   - You MUST NOT call any tools (do NOT call request_missing_document, update_application_status, etc.).
   - You MUST TERMINATE immediately with action_type='TERMINATE', tool=null, is_terminal=true, terminal_outcome='WAITING_FOR_APPLICANT'.
2. Missing Required Documents:
   - If missing required documents and currentStatus is 'SUBMITTED' or 'PROCESSING':
     - You MUST propose update_application_status with new_status='WAITING_FOR_DOCUMENTS', is_terminal=true, terminal_outcome='WAITING_FOR_APPLICANT'.
     - Do NOT propose request_missing_document (document request workflows are handled after transitioning status).
   - If missing required documents and currentStatus is already 'WAITING_FOR_DOCUMENTS':
     - You MUST TERMINATE with action_type='TERMINATE', tool=null, is_terminal=true, terminal_outcome='WAITING_FOR_APPLICANT'.
     - Do NOT call request_missing_document repeatedly.
3. Documents Complete in WAITING_FOR_DOCUMENTS:
   - If all required documents are present and currentStatus is 'WAITING_FOR_DOCUMENTS':
     - Propose update_application_status with new_status='PROCESSING', is_terminal=false, terminal_outcome=null to resume processing.
4. Document OCR & Verification Pipeline (when documents are complete and status is 'PROCESSING'):
   - If any document is unprocessed: call process_document with document_id of the first unprocessed document.
   - If any document processing failed: call update_application_status with new_status='EXCEPTION', is_terminal=true, terminal_outcome='MANUAL_REVIEW_REQUIRED'.
   - If any document has validation mismatches or manual review flags: call update_application_status with new_status='EXCEPTION', is_terminal=true, terminal_outcome='MANUAL_REVIEW_REQUIRED'.
   - If all documents are validated: call update_application_status with new_status='VERIFICATION_IN_PROGRESS'.
5. Academic Eligibility Check:
   - If currentStatus is 'VERIFICATION_IN_PROGRESS': call update_application_status with new_status='ELIGIBILITY_CHECK'.
   - If currentStatus is 'ELIGIBILITY_CHECK': call check_eligibility with application_id.
6. Academic Eligibility Evaluation & Completion:
   - If currentStatus is 'ELIGIBLE' and deterministic eligibility result is ELIGIBLE:
     call update_application_status with new_status='PROCESSING_COMPLETE', is_terminal=true, terminal_outcome='COMPLETED'.
   - If deterministic eligibility evaluation is 'INELIGIBLE':
     call update_application_status with new_status='EXCEPTION', parameters containing reason, is_terminal=true, terminal_outcome='MANUAL_REVIEW_REQUIRED' (requires administrative confirmation before final rejection until Increment 17).
   - If deterministic eligibility evaluation is 'NEEDS_REVIEW':
     call update_application_status with new_status='EXCEPTION', parameters containing reason, is_terminal=true, terminal_outcome='MANUAL_REVIEW_REQUIRED'.

Available Registered Tools:
1. get_application: {"application_id": "string"}
2. get_program_requirements: {"programme_id": "string"}
3. check_document_completeness: {"application_id": "string"}
4. process_document: {"document_id": "string"}
5. extract_document_data: {"document_id": "string"}
6. verify_document: {"document_id": "string"}
7. compare_applicant_details: {"document_id": "string", "application_id": "string"}
8. check_eligibility: {"application_id": "string"}
9. create_exception: {"application_id": "string", "exception_type": "string", "description": "string", "severity": "MEDIUM"}
10. request_missing_document: {"application_id": "string", "document_type": "string"}
11. update_application_status: {"application_id": "string", "new_status": "string", "reason": "string (optional)"}
12. send_notification: {"user_id": "string", "title": "string", "description": "string"}
(Note: Internal system tools such as 'record_audit_event' are managed by the orchestrator and must not be proposed.)

Strict Security & Guardrail Policies:
- You must NEVER make direct database modifications.
- You must NEVER declare document authenticity or override verification results.
- You must NEVER decide academic eligibility yourself; always invoke check_eligibility.
- You must NEVER propose status transitions to ELIGIBLE or INELIGIBLE directly; INELIGIBLE evaluations must be routed to EXCEPTION for administrative confirmation.
- You must NEVER jump to PROCESSING_COMPLETE without a deterministic eligibility result.
- Do NOT include hidden chain-of-thought or reasoning tokens. The rationale must be a single concise sentence.

Output Schema:
{
  "action_type": "TOOL_CALL" or "TERMINATE",
  "tool": "tool_name" (null if TERMINATE),
  "parameters": {"param_key": "param_value"},
  "rationale": "Concise 1-sentence explanation of planned action",
  "stage": "ACT",
  "is_terminal": boolean,
  "terminal_outcome": "COMPLETED" | "WAITING_FOR_APPLICANT" | "MANUAL_REVIEW_REQUIRED" | "DEPENDENCY_PENDING" | "FAILED" (or null)
}
"""


def _strip_json_fences(content: str) -> str:
    """Strip markdown code fences from JSON text."""
    clean = content.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return clean


# =====================================================================
# Model-Backed Planning Strategy
# =====================================================================

class LLMPlanningStrategy(PlanningStrategy):
    """
    Pluggable, model-backed planning strategy implementing the PlanningStrategy interface.
    Validates model output proposals against strict schemas and domain guardrails.
    Gracefully falls back to DeterministicPlanningStrategy on any provider or validation failure.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        fallback_strategy: PlanningStrategy | None = None,
        fallback_enabled: bool = True,
        db: Database | None = None,
    ):
        self.provider = provider
        self.fallback_strategy = fallback_strategy or DeterministicPlanningStrategy()
        self.fallback_enabled = fallback_enabled
        self.db = db
        self.planner_name = "LLM"
        self._fallback_occurred_this_run = False
        self.last_iteration_fallback = False
        self.last_fallback_reason: str | None = None

    def plan_next_action(
        self,
        observation: ApplicationObservation,
        iteration: int,
    ) -> tuple[PlannedAction | None, OrchestrationOutcome | None, str | None]:
        """
        Evaluate observation via LLM provider. On failure or out-of-policy output,
        falls back to deterministic planner if enabled.
        """
        if iteration == 1:
            self._fallback_occurred_this_run = False
        self.last_iteration_fallback = False
        self.last_fallback_reason = None

        if self.provider is None:
            reason_summary = "LLM provider is not configured or unavailable"
            logger.info("%s; using deterministic fallback planner.", reason_summary)
            if self.fallback_enabled:
                self.last_iteration_fallback = True
                self._fallback_occurred_this_run = True
                self.last_fallback_reason = reason_summary
                self._record_fallback_audit(observation.application_id, reason_summary)
                fallback_action, fallback_outcome, fallback_rationale = self.fallback_strategy.plan_next_action(
                    observation, iteration
                )
                if fallback_action is not None:
                    fallback_action.planner = "FALLBACK"
                    fallback_action.fallback_used = True
                    fallback_action.fallback_reason = reason_summary
                return fallback_action, fallback_outcome, fallback_rationale

            return (
                None,
                OrchestrationOutcome.FAILED,
                f"Model-backed planning failed without fallback: {reason_summary}.",
            )

        sanitized_obs = sanitize_observation_for_llm(observation)
        user_prompt = (
            f"Iteration: {iteration}\n"
            f"Observation:\n{json.dumps(sanitized_obs, indent=2)}"
        )

        try:
            raw_response = self.provider.generate_plan_proposal(
                system_prompt=SYSTEM_PLANNING_PROMPT,
                user_prompt=user_prompt,
            )
            clean_json = _strip_json_fences(raw_response)
            proposal = LLMPlanProposal.model_validate_json(clean_json)

            # Enforce Domain Guardrails
            planned_action, outcome, rationale = self._validate_and_build_action(proposal, observation)
            return planned_action, outcome, rationale

        except Exception as exc:
            safe_error_type = exc.__class__.__name__
            safe_message = str(exc)
            # Sanitize message to prevent exposing internal stack details or sensitive data
            if len(safe_message) > 150:
                safe_message = safe_message[:147] + "..."

            reason_summary = f"LLM planning rejected ({safe_error_type}): {safe_message}"

            action_name = "llm_proposal_rejected"
            if isinstance(exc, (LLMProviderTimeoutError, LLMProviderConnectionError, LLMProviderHTTPError)):
                action_name = "Deterministic fallback invoked"

            if self.fallback_enabled:
                self.last_iteration_fallback = True
                self._fallback_occurred_this_run = True
                self.last_fallback_reason = reason_summary
                logger.warning("%s. Delegating to deterministic fallback planner.", reason_summary)
                self._record_fallback_audit(observation.application_id, reason_summary, action=action_name)
                fallback_action, fallback_outcome, fallback_rationale = self.fallback_strategy.plan_next_action(
                    observation, iteration
                )
                if fallback_action is not None:
                    fallback_action.planner = "FALLBACK"
                    fallback_action.fallback_used = True
                    fallback_action.fallback_reason = reason_summary
                return fallback_action, fallback_outcome, fallback_rationale

            logger.warning("%s. Fallback is disabled; halting planning.", reason_summary)
            return (
                None,
                OrchestrationOutcome.FAILED,
                f"Model-backed planning failed without fallback: {reason_summary}",
            )

    def _validate_terminal_outcome(
        self,
        terminal_outcome: OrchestrationOutcome | None,
        action_type: str,
        tool_clean: str | None,
        parameters: dict[str, Any],
        observation: ApplicationObservation,
    ) -> None:
        """
        Validate model-proposed terminal outcomes against deterministic workflow state and evidence.
        Enforces:
        - A model cannot report COMPLETED while the application is in DRAFT, SUBMITTED, PROCESSING,
          or another unfinished state, or without deterministic eligibility evidence.
        - WAITING_FOR_APPLICANT is valid only when awaiting submission (DRAFT) or missing documents.
        - MANUAL_REVIEW_REQUIRED is valid only when exceptions, failures, or mismatches exist.
        - DEPENDENCY_PENDING is valid only when calling external integration tools or in ELIGIBILITY_CHECK.
        - ALREADY_RUNNING is forbidden.
        """
        if not terminal_outcome:
            if action_type == "TERMINATE":
                raise ValueError("TERMINATE action proposal must specify a valid terminal_outcome.")
            return

        outcome_val = terminal_outcome.value if hasattr(terminal_outcome, "value") else str(terminal_outcome)

        if outcome_val == OrchestrationOutcome.FAILED.value:
            raise ValueError(
                f"Invalid terminal outcome: Model-proposed 'FAILED' is not permitted for application in status "
                f"'{observation.current_status}' without an explicitly represented, validated backend failure condition."
            )

        # Enforce Rule 1: DRAFT state must terminate with WAITING_FOR_APPLICANT
        if observation.current_status == "DRAFT":
            if outcome_val != OrchestrationOutcome.WAITING_FOR_APPLICANT.value:
                raise ValueError(
                    f"Invalid terminal outcome: Model cannot report '{outcome_val}' for 'DRAFT'. "
                    f"Must terminate with 'WAITING_FOR_APPLICANT'."
                )
            if action_type != "TERMINATE":
                raise ValueError(
                    "Domain guardrail violation: Tool execution is prohibited while application is in 'DRAFT' status."
                )
            return

        missing_docs = bool(observation.missing_document_types) or not observation.is_document_complete

        # Enforce Rules 2 & 3 for TERMINATE proposals: SUBMITTED or PROCESSING with missing documents cannot terminate directly
        if observation.current_status in ("SUBMITTED", "PROCESSING") and missing_docs and action_type == "TERMINATE":
            raise ValueError(
                f"Domain guardrail violation: Application in '{observation.current_status}' status with missing documents "
                f"cannot terminate directly; it must transition to 'WAITING_FOR_DOCUMENTS' via update_application_status."
            )

        # Enforce Rule 4 for TERMINATE proposals: WAITING_FOR_DOCUMENTS with missing documents must terminate with WAITING_FOR_APPLICANT
        if observation.current_status == "WAITING_FOR_DOCUMENTS" and missing_docs and action_type == "TERMINATE":
            if outcome_val != OrchestrationOutcome.WAITING_FOR_APPLICANT.value:
                raise ValueError(
                    f"Invalid terminal outcome: Application in 'WAITING_FOR_DOCUMENTS' status with missing documents "
                    f"must terminate with 'WAITING_FOR_APPLICANT', not '{outcome_val}'."
                )

        if outcome_val == OrchestrationOutcome.ALREADY_RUNNING.value:
            raise ValueError(
                "Forbidden terminal outcome: 'ALREADY_RUNNING' is an internal concurrency state and cannot be proposed."
            )

        if outcome_val == OrchestrationOutcome.COMPLETED.value:
            # Model cannot report COMPLETED for unfinished application statuses
            unfinished_statuses = (
                "DRAFT",
                "SUBMITTED",
                "PROCESSING",
                "WAITING_FOR_DOCUMENTS",
                "VERIFICATION_IN_PROGRESS",
                "ELIGIBILITY_CHECK",
                "EXCEPTION",
                "INELIGIBLE",
            )
            if observation.current_status in unfinished_statuses:
                raise ValueError(
                    f"Invalid terminal outcome: Model cannot report 'COMPLETED' while application is in '{observation.current_status}' status."
                )

            # A completion outcome must never bypass deterministic eligibility evaluation or required evidence
            if not observation.eligibility_result or observation.eligibility_result.get("status") != "ELIGIBLE":
                raise ValueError(
                    "Invalid terminal outcome: Model cannot report 'COMPLETED' without a deterministic eligibility result of 'ELIGIBLE'."
                )

            # If proposed via TOOL_CALL, tool must transition to PROCESSING_COMPLETE
            if action_type == "TOOL_CALL":
                if tool_clean != ToolName.UPDATE_APPLICATION_STATUS.value or parameters.get("new_status") != "PROCESSING_COMPLETE":
                    raise ValueError(
                        "Invalid terminal outcome: Terminal 'COMPLETED' tool call must update application status to 'PROCESSING_COMPLETE'."
                    )
            elif action_type == "TERMINATE":
                if observation.current_status != "PROCESSING_COMPLETE":
                    raise ValueError(
                        f"Invalid terminal outcome: Model cannot TERMINATE with 'COMPLETED' while application status is '{observation.current_status}'."
                    )

        elif outcome_val == OrchestrationOutcome.WAITING_FOR_APPLICANT.value:
            # Valid when application is in DRAFT (awaiting applicant submission)
            if observation.current_status == "DRAFT":
                return
            # Valid in WAITING_FOR_DOCUMENTS ONLY when required documents are actually missing
            if observation.current_status == "WAITING_FOR_DOCUMENTS":
                if not observation.is_document_complete or bool(observation.missing_document_types):
                    return
                raise ValueError(
                    "Invalid terminal outcome: Cannot report 'WAITING_FOR_APPLICANT' when all required documents "
                    "are complete for status 'WAITING_FOR_DOCUMENTS'. Processing must resume."
                )
            # Valid in SUBMITTED or PROCESSING if missing documents and transitioning to WAITING_FOR_DOCUMENTS
            if (
                observation.current_status in ("SUBMITTED", "PROCESSING")
                and (not observation.is_document_complete or bool(observation.missing_document_types))
                and action_type == "TOOL_CALL"
                and tool_clean == ToolName.UPDATE_APPLICATION_STATUS.value
                and parameters.get("new_status") == "WAITING_FOR_DOCUMENTS"
            ):
                return
            raise ValueError(
                f"Invalid terminal outcome: Cannot report 'WAITING_FOR_APPLICANT' for application in '{observation.current_status}' "
                f"status with document completeness={observation.is_document_complete}."
            )

        elif outcome_val == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED.value:
            # Valid only when independent backend workflow evidence exists:
            # an existing EXCEPTION status, failed documents, validation mismatches,
            # manual-review documents, or eligibility NEEDS_REVIEW/INELIGIBLE. A proposed status change or bare tool call
            # cannot serve as its own justification.
            has_independent_evidence = (
                observation.current_status in ("EXCEPTION", "INELIGIBLE")
                or bool(observation.failed_documents)
                or bool(observation.mismatched_documents)
                or bool(observation.manual_review_documents)
                or (
                    bool(observation.eligibility_result)
                    and observation.eligibility_result.get("status") in ("NEEDS_REVIEW", "INELIGIBLE")
                )
            )
            if not has_independent_evidence:
                raise ValueError(
                    f"Invalid terminal outcome: 'MANUAL_REVIEW_REQUIRED' requires independent workflow evidence "
                    f"(existing EXCEPTION or INELIGIBLE status, failed documents, validation mismatches, manual-review documents, or eligibility NEEDS_REVIEW/INELIGIBLE). "
                    f"Current status '{observation.current_status}' lacks independent failure or exception evidence."
                )

        elif outcome_val == OrchestrationOutcome.DEPENDENCY_PENDING.value:
            # Valid when in ELIGIBILITY_CHECK or invoking external dependency tool
            dependency_tools = (
                ToolName.CHECK_ELIGIBILITY.value,
                ToolName.SEND_NOTIFICATION.value,
                ToolName.CREATE_EXCEPTION.value,
                ToolName.REQUEST_MISSING_DOCUMENT.value,
            )
            if observation.current_status == "ELIGIBILITY_CHECK" or (
                action_type == "TOOL_CALL" and tool_clean in dependency_tools
            ):
                return
            raise ValueError(
                f"Invalid terminal outcome: Cannot report 'DEPENDENCY_PENDING' for status '{observation.current_status}' without active dependency tool call."
            )

        elif outcome_val == OrchestrationOutcome.FAILED.value:
            # Model cannot unilaterally declare an application run failed without an
            # explicitly represented, validated backend failure condition.
            raise ValueError(
                f"Invalid terminal outcome: Model-proposed 'FAILED' is not permitted for application in status "
                f"'{observation.current_status}' without an explicitly represented, validated backend failure condition."
            )

    def _validate_and_build_action(
        self,
        proposal: LLMPlanProposal,
        observation: ApplicationObservation,
    ) -> tuple[PlannedAction | None, OrchestrationOutcome | None, str | None]:
        """
        Strictly enforce application policy and safety guardrails on model proposals.
        """
        # Validate terminal outcome consistency
        if proposal.is_terminal and proposal.terminal_outcome is None:
            raise ValueError("Terminal proposal (is_terminal=True) must specify a valid terminal_outcome.")
        if not proposal.is_terminal and proposal.terminal_outcome is not None:
            raise ValueError("Non-terminal proposal (is_terminal=False) cannot specify a terminal_outcome.")

        if proposal.action_type == "TERMINATE":
            if not proposal.terminal_outcome:
                raise ValueError("TERMINATE action proposal must specify a valid terminal_outcome.")
            self._validate_terminal_outcome(
                terminal_outcome=proposal.terminal_outcome,
                action_type="TERMINATE",
                tool_clean=None,
                parameters={},
                observation=observation,
            )
            # Evaluate allowed outcomes for current state
            allowed_outcomes = ALLOWED_TERMINAL_OUTCOMES_BY_STATUS.get(observation.current_status, set())
            if proposal.terminal_outcome not in allowed_outcomes:
                raise ValueError(
                    f"Terminal outcome '{proposal.terminal_outcome.value}' is not permitted for application status '{observation.current_status}'."
                )
            return None, proposal.terminal_outcome, proposal.rationale

        if proposal.action_type != "TOOL_CALL":
            raise ValueError(f"Unrecognized action_type '{proposal.action_type}'. Must be 'TOOL_CALL' or 'TERMINATE'.")

        if not proposal.tool:
            raise ValueError("TOOL_CALL proposal missing required 'tool' field.")

        tool_clean = proposal.tool.value if hasattr(proposal.tool, "value") else str(proposal.tool).lower()
        if tool_clean not in TOOL_REGISTRY:
            raise ValueError(f"Proposed tool '{tool_clean}' is not in the registered tool catalog.")

        # Disallow internal-only system tools
        if tool_clean == ToolName.RECORD_AUDIT_EVENT.value:
            raise ValueError(
                "Forbidden tool call: 'record_audit_event' is an internal system tool and cannot be proposed as a workflow action."
            )

        # Check forbidden parameter keys
        for k in proposal.parameters.keys():
            if k.lower() in FORBIDDEN_PARAM_KEYS:
                raise ValueError(f"Forbidden parameter key '{k}' detected in proposal.")

        # Check parameter schema, nulls, types, and path traversal
        allowed_schema = TOOL_PARAM_SCHEMAS.get(tool_clean)
        if allowed_schema is not None:
            for k, val in proposal.parameters.items():
                if k not in allowed_schema:
                    raise ValueError(f"Unknown parameter '{k}' for tool '{tool_clean}'. Allowed parameters: {sorted(allowed_schema.keys())}.")
                if val is None:
                    raise ValueError(f"Parameter '{k}' cannot be null.")
                expected_type = allowed_schema[k]
                if not isinstance(val, expected_type):
                    raise ValueError(f"Parameter '{k}' must be of type {expected_type.__name__}, got {type(val).__name__}.")
                if isinstance(val, str):
                    _check_string_for_path_traversal(val, k)

        # Document scoping check
        if "document_id" in proposal.parameters:
            doc_id = proposal.parameters["document_id"]
            uploaded_ids = {d.get("documentId") for d in observation.uploaded_documents if d.get("documentId")}
            if doc_id not in uploaded_ids:
                raise ValueError(
                    f"Document ID '{doc_id}' does not belong to application '{observation.application_id}' or is not uploaded."
                )
            if tool_clean == ToolName.PROCESS_DOCUMENT.value:
                unprocessed_ids = {d.get("documentId") for d in observation.unprocessed_documents if d.get("documentId")}
                if doc_id not in unprocessed_ids:
                    raise ValueError(
                        f"Document ID '{doc_id}' is not in unprocessed documents list for application '{observation.application_id}'."
                    )

        # Hard-gate on CHECK_ELIGIBILITY tool invocation
        if tool_clean == ToolName.CHECK_ELIGIBILITY.value:
            if observation.current_status != "ELIGIBILITY_CHECK":
                raise ValueError(
                    f"Forbidden transition: check_eligibility can only be executed when application is in 'ELIGIBILITY_CHECK' status (current status: '{observation.current_status}')."
                )

        # Hard-gate on transition to ELIGIBILITY_CHECK
        if (
            tool_clean == ToolName.UPDATE_APPLICATION_STATUS.value
            and proposal.parameters.get("new_status") == "ELIGIBILITY_CHECK"
        ):
            required_count = len(observation.required_documents) if hasattr(observation, "required_documents") else 6
            has_all_required = (
                len(observation.uploaded_documents) >= required_count
                and observation.is_document_complete
                and not observation.missing_document_types
            )
            all_validated = (
                not observation.unprocessed_documents
                and not observation.failed_documents
                and not observation.mismatched_documents
                and not observation.manual_review_documents
                and all(
                    d.get("validationStatus") in ("VALIDATED", "VALID")
                    or d.get("status") in ("VALIDATED", "VALID")
                    for d in observation.uploaded_documents
                )
            )
            if observation.current_status != "VERIFICATION_IN_PROGRESS" or not has_all_required or not all_validated:
                raise ValueError(
                    "Forbidden transition: Model cannot propose ELIGIBILITY_CHECK unless application is in "
                    "'VERIFICATION_IN_PROGRESS', all required documents are present, and all documents are validated without errors."
                )

        # Enforce Rule 1: DRAFT state permits no tool executions
        if observation.current_status == "DRAFT":
            raise ValueError(
                "Domain guardrail violation: Tool execution is prohibited while application is in 'DRAFT' status. "
                "Application has not been submitted and must terminate with 'WAITING_FOR_APPLICANT'."
            )

        missing_docs = bool(observation.missing_document_types) or not observation.is_document_complete

        # Enforce Rule 2 & 3: SUBMITTED or PROCESSING with missing required documents
        if observation.current_status in ("SUBMITTED", "PROCESSING") and missing_docs:
            if tool_clean != ToolName.UPDATE_APPLICATION_STATUS.value:
                raise ValueError(
                    f"Domain guardrail violation: Application in '{observation.current_status}' status with missing documents "
                    f"must transition to 'WAITING_FOR_DOCUMENTS' via update_application_status. Tool '{tool_clean}' is not permitted."
                )
            new_status = proposal.parameters.get("new_status")
            if new_status != "WAITING_FOR_DOCUMENTS":
                raise ValueError(
                    f"Domain guardrail violation: Application in '{observation.current_status}' status with missing documents "
                    f"must update status to 'WAITING_FOR_DOCUMENTS', not '{new_status}'."
                )
            proposal.is_terminal = True
            proposal.terminal_outcome = OrchestrationOutcome.WAITING_FOR_APPLICANT

        # Enforce Rule 4: WAITING_FOR_DOCUMENTS state
        if observation.current_status == "WAITING_FOR_DOCUMENTS":
            if missing_docs:
                raise ValueError(
                    f"Domain guardrail violation: Application in 'WAITING_FOR_DOCUMENTS' status with missing documents "
                    f"must terminate with 'WAITING_FOR_APPLICANT'. Tool execution ('{tool_clean}') is prohibited."
                )
            else:
                # Documents complete in WAITING_FOR_DOCUMENTS: must resume PROCESSING
                if tool_clean == ToolName.REQUEST_MISSING_DOCUMENT.value:
                    raise ValueError(
                        "Domain guardrail violation: Cannot request missing documents when all required documents are complete."
                    )
                if tool_clean == ToolName.UPDATE_APPLICATION_STATUS.value:
                    new_status = proposal.parameters.get("new_status")
                    if new_status and new_status != "PROCESSING":
                        raise ValueError(
                            f"Domain guardrail violation: Application in 'WAITING_FOR_DOCUMENTS' with complete documents "
                            f"must transition to 'PROCESSING', not '{new_status}'."
                        )

        # Application ID binding and cross-application validation for application-scoped tools
        app_scoped_tools = (
            ToolName.GET_APPLICATION.value,
            ToolName.CHECK_DOCUMENT_COMPLETENESS.value,
            ToolName.CHECK_ELIGIBILITY.value,
            ToolName.UPDATE_APPLICATION_STATUS.value,
            ToolName.CREATE_EXCEPTION.value,
            ToolName.REQUEST_MISSING_DOCUMENT.value,
            ToolName.COMPARE_APPLICANT_DETAILS.value,
        )
        if tool_clean in app_scoped_tools:
            param_app_id = proposal.parameters.get("application_id")
            if param_app_id and param_app_id != observation.application_id:
                raise ValueError(
                    f"Cross-application access violation: Tool parameter application_id '{param_app_id}' does not match observation '{observation.application_id}'."
                )
            proposal.parameters["application_id"] = observation.application_id

        # Guardrails on get_program_requirements
        if tool_clean == ToolName.GET_PROGRAM_REQUIREMENTS.value:
            param_prog_id = proposal.parameters.get("programme_id")
            if not param_prog_id or not isinstance(param_prog_id, str):
                proposal.parameters["programme_id"] = observation.programme_id

        # Guardrails on update_application_status
        if tool_clean == ToolName.UPDATE_APPLICATION_STATUS.value:
            new_status = proposal.parameters.get("new_status")
            if not new_status or new_status not in ALLOWED_APPLICATION_STATUSES:
                raise ValueError(f"Invalid or missing new_status '{new_status}' in application status update.")

            # Model cannot jump directly to ELIGIBLE without matching deterministic result
            if new_status == "ELIGIBLE":
                if not observation.eligibility_result or observation.eligibility_result.get("status") != "ELIGIBLE":
                    raise ValueError(
                        f"Forbidden transition: Model cannot arbitrarily set status to 'ELIGIBLE'. Must invoke check_eligibility."
                    )
            # In Increment 16, INELIGIBLE evaluations route to EXCEPTION for admin confirmation
            if new_status == "INELIGIBLE":
                raise ValueError(
                    "Forbidden transition: Applications evaluated as INELIGIBLE must be routed to 'EXCEPTION' for administrative confirmation."
                )

            # Model cannot jump to PROCESSING_COMPLETE without deterministic eligibility result indicating ELIGIBLE
            if new_status == "PROCESSING_COMPLETE" and (
                not observation.eligibility_result or observation.eligibility_result.get("status") != "ELIGIBLE"
            ):
                raise ValueError(
                    "Forbidden transition: Cannot transition to 'PROCESSING_COMPLETE' unless eligibility result is deterministically 'ELIGIBLE'."
                )

            # Model cannot jump to VERIFICATION_IN_PROGRESS if documents are unprocessed or failing
            if new_status == "VERIFICATION_IN_PROGRESS" and (
                observation.unprocessed_documents
                or observation.failed_documents
                or observation.mismatched_documents
                or not observation.is_document_complete
            ):
                raise ValueError(
                    "Forbidden transition: Cannot transition to 'VERIFICATION_IN_PROGRESS' while documents are missing, unprocessed, or mismatched."
                )

            # Model cannot transition status to EXCEPTION without independent evidence
            if new_status == "EXCEPTION" and not (
                observation.current_status in ("EXCEPTION", "INELIGIBLE")
                or bool(observation.failed_documents)
                or bool(observation.mismatched_documents)
                or bool(observation.manual_review_documents)
                or (
                    bool(observation.eligibility_result)
                    and observation.eligibility_result.get("status") in ("NEEDS_REVIEW", "INELIGIBLE")
                )
            ):
                raise ValueError(
                    "Forbidden transition: Cannot transition application to 'EXCEPTION' without independent evidence of "
                    "document failure, validation mismatch, manual-review condition, or eligibility review/ineligibility."
                )

        # Guardrails on process_document, extract_document_data, verify_document
        if tool_clean in (
            ToolName.PROCESS_DOCUMENT.value,
            ToolName.EXTRACT_DOCUMENT_DATA.value,
            ToolName.VERIFY_DOCUMENT.value,
        ):
            doc_id = proposal.parameters.get("document_id")
            if not doc_id or not isinstance(doc_id, str):
                raise ValueError(f"{tool_clean} requires a non-empty string 'document_id' parameter.")

        # Guardrails on compare_applicant_details
        if tool_clean == ToolName.COMPARE_APPLICANT_DETAILS.value:
            doc_id = proposal.parameters.get("document_id")
            if not doc_id or not isinstance(doc_id, str):
                raise ValueError("compare_applicant_details requires a non-empty string 'document_id' parameter.")

        # Guardrails on create_exception
        if tool_clean == ToolName.CREATE_EXCEPTION.value:
            exc_type = proposal.parameters.get("exception_type")
            desc = proposal.parameters.get("description")
            if not exc_type or not isinstance(exc_type, str):
                raise ValueError("create_exception requires a non-empty string 'exception_type' parameter.")
            if not desc or not isinstance(desc, str):
                raise ValueError("create_exception requires a non-empty string 'description' parameter.")
            if not proposal.parameters.get("severity"):
                proposal.parameters["severity"] = "MEDIUM"

        # Guardrails on request_missing_document
        if tool_clean == ToolName.REQUEST_MISSING_DOCUMENT.value:
            if observation.is_document_complete and not observation.missing_document_types:
                raise ValueError("Domain guardrail violation: Cannot request missing documents when all required documents are complete.")
            doc_type = proposal.parameters.get("document_type")
            if not doc_type or not isinstance(doc_type, str):
                raise ValueError("request_missing_document requires a non-empty string 'document_type' parameter.")
            if observation.missing_document_types and doc_type not in observation.missing_document_types:
                raise ValueError(
                    f"Domain guardrail violation: Document type '{doc_type}' is not in missing documents list {observation.missing_document_types}."
                )

        # Guardrails on send_notification
        if tool_clean == ToolName.SEND_NOTIFICATION.value:
            title = proposal.parameters.get("title")
            desc = proposal.parameters.get("description")
            if not title or not isinstance(title, str):
                raise ValueError("send_notification requires a non-empty string 'title' parameter.")
            if not desc or not isinstance(desc, str):
                raise ValueError("send_notification requires a non-empty string 'description' parameter.")
            if not proposal.parameters.get("user_id"):
                proposal.parameters["user_id"] = observation.user_id or "applicant_user"
            if not proposal.parameters.get("applicant_id"):
                proposal.parameters["applicant_id"] = observation.applicant_id

        # Validate terminal outcome if proposal declares is_terminal
        if proposal.is_terminal and proposal.terminal_outcome:
            self._validate_terminal_outcome(
                terminal_outcome=proposal.terminal_outcome,
                action_type="TOOL_CALL",
                tool_clean=tool_clean,
                parameters=proposal.parameters,
                observation=observation,
            )

        # Evaluate proposal against allowed tools and terminal outcomes for current state
        allowed_tools = ALLOWED_TOOLS_BY_STATUS.get(observation.current_status, set())
        if tool_clean not in allowed_tools:
            raise ValueError(
                f"Tool '{tool_clean}' is not permitted for application status '{observation.current_status}'."
            )
        if proposal.is_terminal and proposal.terminal_outcome:
            allowed_outcomes = ALLOWED_TERMINAL_OUTCOMES_BY_STATUS.get(observation.current_status, set())
            if proposal.terminal_outcome not in allowed_outcomes:
                raise ValueError(
                    f"Terminal outcome '{proposal.terminal_outcome.value}' is not permitted for status '{observation.current_status}'."
                )

        # Build PlannedAction
        planned_action = PlannedAction(
            tool=proposal.tool,
            parameters=proposal.parameters,
            rationale=proposal.rationale,
            stage=proposal.stage,
            is_terminal=proposal.is_terminal,
            terminal_outcome=proposal.terminal_outcome,
            planner="LLM",
            fallback_used=False,
            fallback_reason=None,
        )

        terminal_outcome = proposal.terminal_outcome if proposal.is_terminal else None
        return planned_action, terminal_outcome, proposal.rationale

    def _record_fallback_audit(
        self,
        application_id: str,
        reason: str,
        action: str = "llm_proposal_rejected",
    ) -> None:
        """
        Record a sanitized FALLBACK audit record in agent_activity collection.
        Never logs credentials, full prompts, or raw model text.
        """
        if self.db is None:
            return

        try:
            system_user = {
                "_id": "system_orchestrator",
                "role": "system",
                "full_name": "Autonomous Agent Orchestrator",
            }
            tool_record_audit_event(
                db=self.db,
                current_user=system_user,
                application_id=application_id,
                stage=WorkflowStage.PLAN.value,
                tool="llm_planner",
                action=action,
                result=reason,
                status="FALLBACK",
            )
        except Exception as e:
            logger.debug("Could not record fallback audit event: %s", e)
