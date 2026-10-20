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
9. create_exception: {"exception_type": "string", "description": "string", "severity": "MEDIUM"}
10. request_missing_document: {"application_id": "string", "document_type": "string"}
11. update_application_status: {"application_id": "string", "new_status": "string"}
12. send_notification: {"title": "string", "description": "string"}
13. record_audit_event: {"action": "string", "result": "string"}

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
            return None, proposal.terminal_outcome, proposal.rationale

        if proposal.action_type != "TOOL_CALL":
            raise ValueError(f"Unrecognized action_type '{proposal.action_type}'. Must be 'TOOL_CALL' or 'TERMINATE'.")

        if not proposal.tool:
            raise ValueError("TOOL_CALL proposal missing required 'tool' field.")

        tool_clean = proposal.tool.value if hasattr(proposal.tool, "value") else str(proposal.tool).lower()
        if tool_clean not in TOOL_REGISTRY:
            raise ValueError(f"Proposed tool '{tool_clean}' is not in the registered tool catalog.")

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

        # Guardrails on process_document
        if tool_clean == ToolName.PROCESS_DOCUMENT.value:
            doc_id = proposal.parameters.get("document_id")
            if not doc_id or not isinstance(doc_id, str):
                raise ValueError("process_document requires a non-empty string 'document_id' parameter.")

        # Guardrails on check_eligibility
        if tool_clean == ToolName.CHECK_ELIGIBILITY.value:
            app_id = proposal.parameters.get("application_id")
            if not app_id or app_id != observation.application_id:
                proposal.parameters["application_id"] = observation.application_id

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
