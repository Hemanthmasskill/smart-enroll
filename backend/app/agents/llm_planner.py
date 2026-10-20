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
)
from app.agents.providers import LLMProvider, LLMProviderError
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
11. update_application_status: {"application_id": "string", "new_status": "string"}
12. send_notification: {"user_id": "string", "title": "string", "description": "string"}
(Note: Internal system tools such as 'record_audit_event' are managed by the orchestrator and must not be proposed.)

Strict Admission Workflow Pipeline:
1. If status is 'DRAFT': Wait for applicant (TERMINATE with terminal_outcome='WAITING_FOR_APPLICANT').
2. If missing required documents:
   - If status is not 'WAITING_FOR_DOCUMENTS', call update_application_status with new_status='WAITING_FOR_DOCUMENTS', is_terminal=True, terminal_outcome='WAITING_FOR_APPLICANT'.
   - If already in 'WAITING_FOR_DOCUMENTS', TERMINATE with terminal_outcome='WAITING_FOR_APPLICANT'.
3. If all required documents are present and status is 'WAITING_FOR_DOCUMENTS':
   - Call update_application_status with new_status='PROCESSING'.
4. If documents need OCR processing:
   - Call process_document for the first unprocessed document.
5. If any document processing failed:
   - Call update_application_status with new_status='EXCEPTION', is_terminal=True, terminal_outcome='MANUAL_REVIEW_REQUIRED'.
6. If any document has validation mismatches or manual review flags:
   - Call update_application_status with new_status='EXCEPTION', is_terminal=True, terminal_outcome='MANUAL_REVIEW_REQUIRED'.
7. If all documents are validated and status is 'PROCESSING':
   - Call update_application_status with new_status='VERIFICATION_IN_PROGRESS'.
8. If status is 'VERIFICATION_IN_PROGRESS':
   - Call update_application_status with new_status='ELIGIBILITY_CHECK'.
9. If status is 'ELIGIBILITY_CHECK':
   - Call check_eligibility with application_id.
10. If status is 'ELIGIBLE' or 'INELIGIBLE':
    - If eligibility result is present, call update_application_status with new_status='PROCESSING_COMPLETE', is_terminal=True, terminal_outcome='COMPLETED'.

Strict Security & Guardrail Policies:
- You must NEVER make direct database modifications.
- You must NEVER declare document authenticity or override verification results.
- You must NEVER decide academic eligibility yourself; always invoke check_eligibility.
- You must NEVER propose status transitions to ELIGIBLE or INELIGIBLE directly.
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

    def plan_next_action(
        self,
        observation: ApplicationObservation,
        iteration: int,
    ) -> tuple[PlannedAction | None, OrchestrationOutcome | None, str | None]:
        """
        Evaluate observation via LLM provider. On failure or out-of-policy output,
        falls back to deterministic planner if enabled.
        """
        if self.provider is None:
            logger.info("LLM provider is not configured; using deterministic fallback planner.")
            return self.fallback_strategy.plan_next_action(observation, iteration)

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
            logger.warning("%s. Delegating to deterministic fallback planner.", reason_summary)

            self._record_fallback_audit(observation.application_id, reason_summary)

            if self.fallback_enabled:
                return self.fallback_strategy.plan_next_action(observation, iteration)

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
            )
            if observation.current_status in unfinished_statuses:
                raise ValueError(
                    f"Invalid terminal outcome: Model cannot report 'COMPLETED' while application is in '{observation.current_status}' status."
                )

            # A completion outcome must never bypass deterministic eligibility evaluation or required evidence
            if not observation.eligibility_result:
                raise ValueError(
                    "Invalid terminal outcome: Model cannot report 'COMPLETED' without deterministic eligibility result evidence."
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
            # or manual-review documents. A proposed status change or bare tool call
            # cannot serve as its own justification.
            has_independent_evidence = (
                observation.current_status == "EXCEPTION"
                or bool(observation.failed_documents)
                or bool(observation.mismatched_documents)
                or bool(observation.manual_review_documents)
            )
            if not has_independent_evidence:
                raise ValueError(
                    f"Invalid terminal outcome: 'MANUAL_REVIEW_REQUIRED' requires independent workflow evidence "
                    f"(existing EXCEPTION status, failed documents, validation mismatches, or manual-review documents). "
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

            # Model cannot jump directly to ELIGIBLE or INELIGIBLE
            if new_status in ("ELIGIBLE", "INELIGIBLE"):
                raise ValueError(
                    f"Forbidden transition: Model cannot arbitrarily set status to '{new_status}'. Must invoke check_eligibility."
                )

            # Model cannot jump to PROCESSING_COMPLETE without deterministic eligibility result
            if new_status == "PROCESSING_COMPLETE" and not observation.eligibility_result:
                raise ValueError(
                    "Forbidden transition: Cannot transition to 'PROCESSING_COMPLETE' without deterministic eligibility result."
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
                observation.current_status == "EXCEPTION"
                or bool(observation.failed_documents)
                or bool(observation.mismatched_documents)
                or bool(observation.manual_review_documents)
            ):
                raise ValueError(
                    "Forbidden transition: Cannot transition application to 'EXCEPTION' without independent evidence of "
                    "document failure, validation mismatch, or manual-review condition."
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
            doc_type = proposal.parameters.get("document_type")
            if not doc_type or not isinstance(doc_type, str):
                raise ValueError("request_missing_document requires a non-empty string 'document_type' parameter.")

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

        # Build PlannedAction
        planned_action = PlannedAction(
            tool=proposal.tool,
            parameters=proposal.parameters,
            rationale=proposal.rationale,
            stage=proposal.stage,
            is_terminal=proposal.is_terminal,
            terminal_outcome=proposal.terminal_outcome,
        )

        terminal_outcome = proposal.terminal_outcome if proposal.is_terminal else None
        return planned_action, terminal_outcome, proposal.rationale

    def _record_fallback_audit(self, application_id: str, reason: str) -> None:
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
                action="Deterministic fallback invoked",
                result=reason,
                status="FALLBACK",
            )
        except Exception as e:
            logger.debug("Could not record fallback audit event: %s", e)
