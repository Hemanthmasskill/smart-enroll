r"""
Smart Enroll -- Real Ollama LLM Integration Verification Utility

Safe, reproducible diagnostic tool to verify that the local Ollama LLM
is fully integrated with Smart Enroll's Increment 15 agent orchestration layer.

Diagnostic checks:
- Check A: Application configuration loading & local Ollama safety constraints
- Check B: Real Ollama provider communication via OpenAICompatibleProvider
- Check C: Actual LLM planning with zero silent fallback to deterministic planner
- Check D: AgentOrchestrator strategy selection and configuration
- Verification Summary: Overall verification result and exit code

Usage (from backend directory):
    ..\backend\.venv\Scripts\python scripts/verify_live_llm.py

Or from repository root:
    backend\.venv\Scripts\python backend/scripts/verify_live_llm.py
"""

import json
from pathlib import Path
import sys
import time
from typing import Any
from unittest.mock import MagicMock
import urllib.parse

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.agents.providers import (
    LLMProvider,
    LLMProviderError,
    LLMSSRFValidationError,
    OpenAICompatibleProvider,
    is_local_endpoint,
    validate_endpoint_url,
)
from app.agents.llm_planner import LLMPlanningStrategy
from app.agents.orchestrator import (
    AgentOrchestrator,
    ApplicationObservation,
    DeterministicPlanningStrategy,
    PlannedAction,
)
from app.schemas.agent import (
    OrchestrationOutcome,
    ToolName,
    WorkflowStage,
)


def log_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def log_step(status: str, check_id: str, description: str) -> None:
    colors = {
        "PASS": "\033[92m[PASS]\033[0m",
        "FAIL": "\033[91m[FAIL]\033[0m",
        "SKIPPED": "\033[93m[SKIPPED]\033[0m",
    }
    label = colors.get(status, f"[{status}]")
    print(f"{label} {check_id} -- {description}")


def sanitize_url_for_display(url: str | None) -> str:
    """
    Sanitize a URL for diagnostic display by retaining only scheme, hostname, and port,
    while stripping path, user credentials, passwords, query parameters, and fragments.
    """
    if not url or not isinstance(url, str):
        return "[not configured]"
    try:
        parsed = urllib.parse.urlparse(url.strip())
        scheme = parsed.scheme or "http"
        hostname = parsed.hostname or "unknown"
        host_display = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        port_str = f":{parsed.port}" if parsed.port else ""
        return f"{scheme}://{host_display}{port_str}"
    except Exception:
        return "[redacted endpoint]"


def format_sanitized_provider_repr(provider: Any) -> str:
    """
    Produce a sanitized diagnostic string representation of a provider,
    ensuring endpoints omit userinfo/query parameters and credentials are never exposed.
    """
    if not provider:
        return "None"
    model = getattr(provider, "model", "unknown")
    api_base = getattr(provider, "api_base", "")
    sanitized_base = sanitize_url_for_display(api_base)
    api_key = getattr(provider, "api_key", None)
    has_key = bool(api_key and str(api_key).strip())
    key_status = "configured (masked)" if has_key else "none"
    timeout = getattr(provider, "timeout_seconds", 0.0)
    return (
        f"OpenAICompatibleProvider(model='{model}', api_base='{sanitized_base}', "
        f"api_key='{key_status}', timeout={timeout}s)"
    )


def validate_local_ollama_endpoint(
    endpoint_url: str,
    provider_name: str,
    allow_local_endpoints: bool,
) -> tuple[bool, str]:
    """
    Validate that the configured provider and endpoint strictly target a local Ollama instance.
    Enforces:
    - Provider must be 'openai_compatible'.
    - Local endpoints must be explicitly permitted (allow_local_endpoints=True).
    - URL destination must pass SSRF validation and match a recognized local loopback hostname/address.
    - Hostname must be a recognized local loopback hostname/address ('localhost', '127.0.0.1', '::1', or *.localhost).
    - Port must be standard Ollama port (11434).
    Prevents accidental prompt or applicant data transmission to remote endpoints.
    """
    if provider_name != "openai_compatible":
        return False, f"Provider '{provider_name}' is not 'openai_compatible'. Local Ollama requires 'openai_compatible'."

    if not allow_local_endpoints:
        return False, "LLM_ALLOW_LOCAL_ENDPOINTS must be enabled for local Ollama."

    if not endpoint_url or not isinstance(endpoint_url, str):
        return False, "Endpoint URL must be a non-empty string."

    if not is_local_endpoint(endpoint_url):
        clean_disp = sanitize_url_for_display(endpoint_url)
        return False, f"Endpoint '{clean_disp}' is not a recognized local loopback hostname/address."

    try:
        clean_url = validate_endpoint_url(endpoint_url, allow_local_endpoints=True)
    except LLMSSRFValidationError as exc:
        return False, f"Endpoint failed SSRF validation: {exc}"

    parsed = urllib.parse.urlparse(clean_url)
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("localhost", "127.0.0.1", "::1") and not hostname.endswith(".localhost"):
        return False, f"Endpoint hostname '{hostname}' is not a recognized local loopback hostname/address."

    if parsed.port != 11434:
        return False, f"Endpoint port {parsed.port} is not the standard local Ollama port (11434)."

    return True, "Valid local Ollama endpoint."


def run_check_a() -> tuple[bool, dict[str, Any]]:
    """
    Check A -- Configuration & Local Ollama Endpoint Safety
    Load settings using existing application configuration system.
    Report provider, model, endpoint, timeout, fallback setting, and local endpoint permission.
    Never expose secret API keys or URL user credentials.
    """
    print("\n--- Running Check A: Configuration Verification ---")
    info = {
        "LLM_PROVIDER": settings.LLM_PROVIDER,
        "LLM_MODEL": settings.LLM_MODEL,
        "LLM_API_BASE": settings.LLM_API_BASE,
        "LLM_TIMEOUT_SECONDS": settings.LLM_TIMEOUT_SECONDS,
        "LLM_TEMPERATURE": settings.LLM_TEMPERATURE,
        "LLM_FALLBACK_TO_DETERMINISTIC": settings.LLM_FALLBACK_TO_DETERMINISTIC,
        "LLM_ALLOW_LOCAL_ENDPOINTS": settings.LLM_ALLOW_LOCAL_ENDPOINTS,
        "LLM_API_KEY_CONFIGURED": bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip()),
    }

    sanitized_endpoint = sanitize_url_for_display(info["LLM_API_BASE"])
    print(f"  * Provider:             {info['LLM_PROVIDER']}")
    print(f"  * Model:                {info['LLM_MODEL']}")
    print(f"  * Endpoint:             {sanitized_endpoint}")
    print(f"  * Timeout:              {info['LLM_TIMEOUT_SECONDS']}s")
    print(f"  * Temperature:          {info['LLM_TEMPERATURE']}")
    print(f"  * Fallback to Det.:     {info['LLM_FALLBACK_TO_DETERMINISTIC']}")
    print(f"  * Allow Local Endpts:   {info['LLM_ALLOW_LOCAL_ENDPOINTS']}")
    print(f"  * API Key Configured:   {info['LLM_API_KEY_CONFIGURED']} (credentials masked)")

    # Assertions
    if not info["LLM_MODEL"]:
        print("  [ERROR] LLM_MODEL is not configured.")
        return False, info

    # Enforce local Ollama endpoint safety
    is_safe, safety_reason = validate_local_ollama_endpoint(
        endpoint_url=info["LLM_API_BASE"],
        provider_name=info["LLM_PROVIDER"],
        allow_local_endpoints=info["LLM_ALLOW_LOCAL_ENDPOINTS"],
    )
    if not is_safe:
        print(f"  [ERROR] Local Ollama endpoint safety check failed: {safety_reason}")
        return False, info

    return True, info


def run_check_b(config_info: dict[str, Any]) -> tuple[bool, OpenAICompatibleProvider | None]:
    """
    Check B -- Real Provider Communication
    Instantiate OpenAICompatibleProvider using actual application settings.
    Send a small, harmless JSON-only request to local Ollama and validate response contract.
    Ensures provider is safely cleaned up on any failure.
    """
    print("\n--- Running Check B: Real Provider Communication ---")

    # Safety check before initiating any provider connection
    is_safe, safety_reason = validate_local_ollama_endpoint(
        endpoint_url=settings.LLM_API_BASE,
        provider_name=settings.LLM_PROVIDER,
        allow_local_endpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
    )
    if not is_safe:
        print(f"  [ERROR] Refusing provider connection: {safety_reason}")
        return False, None

    provider = None
    try:
        provider = OpenAICompatibleProvider(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
            api_base=settings.LLM_API_BASE,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            temperature=settings.LLM_TEMPERATURE,
            allow_local_endpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
        )
        print(f"  * Provider instance: {format_sanitized_provider_repr(provider)}")

        test_system_prompt = (
            "You are a system verification assistant for Smart Enroll. "
            "Reply strictly with a valid JSON object matching: "
            '{"status": "ok", "service": "smart-enroll-verification"}'
        )
        test_user_prompt = "health_check_ping"

        start_time = time.perf_counter()
        raw_response = provider.generate_plan_proposal(
            system_prompt=test_system_prompt,
            user_prompt=test_user_prompt,
        )
        elapsed = time.perf_counter() - start_time
        print(f"  * Round-trip response received in {elapsed:.2f}s")
        print(f"  * Raw response content: {raw_response.strip()[:100]}...")

        # Validate response format
        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            print(f"  [ERROR] Invalid JSON returned by provider: {exc}")
            provider.close()
            return False, None

        if not isinstance(data, dict):
            print(f"  [ERROR] Expected JSON object, got {type(data).__name__}")
            provider.close()
            return False, None

        if data.get("status") != "ok":
            print(f"  [ERROR] Contract violation: expected status 'ok', got '{data.get('status')}'")
            provider.close()
            return False, None

        print("  * Provider response contract verified successfully.")
        return True, provider

    except LLMProviderError as e:
        safe_msg = str(e)[:150]
        print(f"  [ERROR] Provider error ({type(e).__name__}): {safe_msg}")
        if provider:
            provider.close()
        return False, None
    except Exception as e:
        safe_msg = str(e)[:150]
        print(f"  [ERROR] Unexpected error ({type(e).__name__}): {safe_msg}")
        if provider:
            provider.close()
        return False, None


def run_check_c(provider: OpenAICompatibleProvider) -> bool:
    """
    Check C -- Actual LLM Planning (Proving No Silent Fallback)
    Exercise LLMPlanningStrategy with real local Ollama provider.
    Verifies:
    1. Proposal is parsed and strictly satisfies application schema and domain guardrails.
    2. Scenario C1: Active PROCESSING state proposes PROCESS_DOCUMENT without fallback.
    3. Scenario C2: Unsubmitted DRAFT state terminates with WAITING_FOR_APPLICANT.
    4. Scenario C3: Successful LLM planning produces a valid action without fallback invocation,
       and fallback audit telemetry is verified by confirming submission to the audit collection
       through the mocked database.
    """
    print("\n--- Running Check C: Actual LLM Planning (No Fallback) ---")

    # -------------------------------------------------------------
    # Scenario C1: Active workflow advancement (PROCESSING with unprocessed doc)
    # -------------------------------------------------------------
    print("  [Scenario C1] Active Workflow Progression (PROCESSING with unprocessed doc)")
    synth_obs_proc = ApplicationObservation(
        application_id="SYNTH-APP-PROC-001",
        current_status="PROCESSING",
        programme_id="mca",
        applicant_id="APPL-SYNTH-001",
        user_id="USER-SYNTH-001",
        applicant_name="Synthetic Candidate",
        is_document_complete=True,
        missing_document_types=[],
        uploaded_documents=[{
            "documentId": "doc-synth-ocr-01",
            "documentType": "10TH_MARKSHEET",
            "status": "UPLOADED",
        }],
        unprocessed_documents=[{
            "documentId": "doc-synth-ocr-01",
            "documentType": "10TH_MARKSHEET",
            "status": "UPLOADED",
        }],
        failed_documents=[],
        mismatched_documents=[],
        manual_review_documents=[],
        validated_documents=[],
        eligibility_result=None,
    )

    # Isolated strategy with FALLBACK STRICTLY DISABLED to prove real LLM execution
    strategy_no_fallback = LLMPlanningStrategy(
        provider=provider,
        fallback_enabled=False,
    )

    t0 = time.perf_counter()
    action1, outcome1, rationale1 = strategy_no_fallback.plan_next_action(synth_obs_proc, iteration=1)
    t1 = time.perf_counter()
    print(f"  * Planning proposal completed in {t1 - t0:.2f}s")
    print(f"  * Planned Action Tool:    {action1.tool if action1 else None}")
    print(f"  * Planned Action Params:  {action1.parameters if action1 else None}")
    print(f"  * Action Stage:           {action1.stage if action1 else None}")
    print(f"  * Action Rationale:       '{rationale1}'")
    print(f"  * Terminal Outcome:       {outcome1}")

    # Rigorous Scenario C1 assertions based on existing planner contract
    if action1 is None or not isinstance(action1, PlannedAction):
        print("  [FAIL] PlannedAction is None; expected valid PlannedAction instance.")
        return False
    if action1.tool != ToolName.PROCESS_DOCUMENT:
        print(f"  [FAIL] Expected ToolName.PROCESS_DOCUMENT, got {action1.tool}")
        return False
    if action1.parameters.get("document_id") != "doc-synth-ocr-01":
        print(f"  [FAIL] Expected document_id 'doc-synth-ocr-01', got {action1.parameters.get('document_id')}")
        return False
    if action1.stage != WorkflowStage.ACT:
        print(f"  [FAIL] Expected action stage WorkflowStage.ACT, got {action1.stage}")
        return False
    if action1.is_terminal is not False or action1.terminal_outcome is not None:
        print(f"  [FAIL] Expected non-terminal PlannedAction, got is_terminal={action1.is_terminal}, terminal_outcome={action1.terminal_outcome}")
        return False
    if outcome1 is not None:
        print(f"  [FAIL] Expected non-terminal planning outcome None, got {outcome1}")
        return False
    if not rationale1 or not isinstance(rationale1, str):
        print("  [FAIL] Expected non-empty planning rationale string.")
        return False

    # -------------------------------------------------------------
    # Scenario C2: Legitimate waiting state (DRAFT unsubmitted application)
    # -------------------------------------------------------------
    print("\n  [Scenario C2] Legitimate Waiting State (DRAFT awaiting applicant submission)")
    synth_obs_draft = ApplicationObservation(
        application_id="SYNTH-APP-DRAFT-002",
        current_status="DRAFT",
        programme_id="mca",
        applicant_id="APPL-SYNTH-002",
        user_id="USER-SYNTH-002",
        applicant_name="Synthetic Candidate",
        is_document_complete=False,
        missing_document_types=["DEGREE_CERTIFICATE"],
        uploaded_documents=[],
        unprocessed_documents=[],
        failed_documents=[],
        mismatched_documents=[],
        manual_review_documents=[],
        validated_documents=[],
        eligibility_result=None,
    )

    t2 = time.perf_counter()
    action2, outcome2, rationale2 = strategy_no_fallback.plan_next_action(synth_obs_draft, iteration=1)
    t3 = time.perf_counter()
    print(f"  * Planning proposal completed in {t3 - t2:.2f}s")
    print(f"  * Planned Action:         {action2}")
    print(f"  * Terminal Outcome:       {outcome2}")
    print(f"  * Action Rationale:       '{rationale2}'")

    if action2 is not None:
        print(f"  [FAIL] Expected None for DRAFT action, got {action2}")
        return False
    if outcome2 != OrchestrationOutcome.WAITING_FOR_APPLICANT:
        print(f"  [FAIL] Expected WAITING_FOR_APPLICANT outcome, got {outcome2}")
        return False
    if not rationale2 or not isinstance(rationale2, str):
        print("  [FAIL] Expected non-empty planning rationale for DRAFT.")
        return False

    # -------------------------------------------------------------
    # Scenario C3: Verify Configured Fallback Invariant & Telemetry
    # -------------------------------------------------------------
    print("\n  [Scenario C3] Audit Trail Invariant & Fallback Telemetry (Configured Fallback Setting)")

    # 1. Verify successful LLM planning with fallback enabled (application configured state)
    mock_tracker_db = MagicMock()
    mock_tracker_db["applications"].find_one.return_value = None

    fallback_spy = MagicMock(wraps=DeterministicPlanningStrategy())
    strategy_configured = LLMPlanningStrategy(
        provider=provider,
        fallback_strategy=fallback_spy,
        fallback_enabled=settings.LLM_FALLBACK_TO_DETERMINISTIC,
        db=mock_tracker_db,
    )

    action3, outcome3, rationale3 = strategy_configured.plan_next_action(synth_obs_proc, iteration=1)

    if action3 is None or not isinstance(action3, PlannedAction):
        print("  [FAIL] Configured strategy returned invalid PlannedAction.")
        return False
    if action3.tool != ToolName.PROCESS_DOCUMENT:
        print(f"  [FAIL] Expected ToolName.PROCESS_DOCUMENT, got {action3.tool}")
        return False
    if action3.parameters.get("document_id") != "doc-synth-ocr-01":
        print(f"  [FAIL] Expected document_id 'doc-synth-ocr-01', got {action3.parameters.get('document_id')}")
        return False
    if action3.stage != WorkflowStage.ACT:
        print(f"  [FAIL] Expected stage WorkflowStage.ACT, got {action3.stage}")
        return False
    if outcome3 is not None:
        print(f"  [FAIL] Expected non-terminal outcome None, got {outcome3}")
        return False

    if fallback_spy.plan_next_action.called:
        print("  [FAIL] Fallback strategy plan_next_action was called despite valid LLM planning.")
        return False

    if mock_tracker_db["agent_activity"].insert_one.called:
        print("  [FAIL] Audit event was recorded indicating fallback during successful planning.")
        return False

    det_action, det_outcome, det_rationale = DeterministicPlanningStrategy().plan_next_action(synth_obs_proc, iteration=1)
    print(f"  * LLM Action Rationale:          '{rationale3}'")
    print(f"  * Deterministic Fixed Rationale: '{det_action.rationale if det_action else None}'")
    print(f"  * Fallback strategy invoked:     {fallback_spy.plan_next_action.called}")
    print(f"  * Fallback audit event recorded: {mock_tracker_db['agent_activity'].insert_one.called}")

    # 2. Verify fallback telemetry using the actual audit mechanism on simulated failure
    print("\n  [Telemetry Verification] Verifying Fallback Audit Telemetry on Failure")
    test_audit_db = MagicMock()
    test_audit_db["applications"].find_one.return_value = None
    test_fallback_spy = MagicMock(wraps=DeterministicPlanningStrategy())

    failing_provider = MagicMock(spec=LLMProvider)
    failing_provider.generate_plan_proposal.side_effect = LLMProviderError("Simulated failure for audit verification")

    strategy_failing = LLMPlanningStrategy(
        provider=failing_provider,
        fallback_strategy=test_fallback_spy,
        fallback_enabled=True,
        db=test_audit_db,
    )

    fb_action, fb_outcome, fb_rationale = strategy_failing.plan_next_action(synth_obs_proc, iteration=1)

    if not test_fallback_spy.plan_next_action.called:
        print("  [FAIL] Fallback strategy was not invoked during simulated provider failure.")
        return False

    if not test_audit_db["agent_activity"].insert_one.called:
        print("  [FAIL] Fallback audit telemetry failed to invoke insert_one on fallback event.")
        return False

    audit_entry = test_audit_db["agent_activity"].insert_one.call_args[0][0]
    if (
        audit_entry.get("status") != "FALLBACK"
        or audit_entry.get("stage") != WorkflowStage.PLAN.value
        or audit_entry.get("tool") != "llm_planner"
    ):
        print(f"  [FAIL] Recorded fallback audit entry structure is invalid: {audit_entry}")
        return False

    print("  * Verified fallback telemetry: expected audit event correctly submitted to audit collection with status='FALLBACK' through mocked database.")
    print("  * Actual LLM planning verified without silent fallback.")
    return True


def run_check_d() -> bool:
    """
    Check D -- Orchestrator Configuration
    Instantiate AgentOrchestrator using real application settings.
    Confirm it selects LLMPlanningStrategy and properly configures provider and fallback.
    Guarantees orchestrator's provider resources are safely closed upon completion.
    Does NOT invoke any admission workflow or modify database records.
    """
    print("\n--- Running Check D: Orchestrator Strategy Selection ---")
    orchestrator = None
    try:
        # Non-destructive check with db=None (orchestrator __init__ does not access collections)
        orchestrator = AgentOrchestrator(db=None)

        print(f"  * Orchestrator strategy type:  {type(orchestrator.strategy).__name__}")
        print(f"  * Planner name:                {getattr(orchestrator.strategy, 'planner_name', None)}")

        if not isinstance(orchestrator.strategy, LLMPlanningStrategy):
            print("  [FAIL] AgentOrchestrator did not initialize with LLMPlanningStrategy.")
            return False

        if orchestrator.strategy.planner_name != "LLM":
            print(f"  [FAIL] Expected planner_name == 'LLM', got {orchestrator.strategy.planner_name}")
            return False

        strat_provider = orchestrator.strategy.provider
        print(f"  * Bound provider:              {format_sanitized_provider_repr(strat_provider)}")
        if not isinstance(strat_provider, OpenAICompatibleProvider):
            print("  [FAIL] Orchestrator strategy provider is not OpenAICompatibleProvider.")
            return False

        if strat_provider.model != settings.LLM_MODEL:
            print(f"  [FAIL] Expected model '{settings.LLM_MODEL}', got '{strat_provider.model}'")
            return False

        print(f"  * Fallback enabled setting:    {orchestrator.strategy.fallback_enabled}")
        if orchestrator.strategy.fallback_enabled != settings.LLM_FALLBACK_TO_DETERMINISTIC:
            print("  [FAIL] Fallback enabled mismatch with application settings.")
            return False

        print("  * Orchestrator configuration successfully selects real LLM strategy.")
        return True

    except Exception as e:
        print(f"  [FAIL] Orchestrator initialization error: {e}")
        return False
    finally:
        if orchestrator is not None:
            strat_provider = getattr(getattr(orchestrator, "strategy", None), "provider", None)
            if strat_provider and hasattr(strat_provider, "close"):
                strat_provider.close()


def main() -> int:
    log_header("Smart Enroll -- Live Ollama LLM Integration Verification")
    results = {}

    # Check A: Configuration
    ok_a, config_info = run_check_a()
    results["Check A (Configuration)"] = "PASS" if ok_a else "FAIL"
    log_step(results["Check A (Configuration)"], "Check A", "Application Configuration Loading & Safety")

    if not ok_a:
        log_header("Verification Summary: FAILED at Check A")
        return 1

    # Check B & C with guaranteed provider cleanup
    provider = None
    try:
        ok_b, provider = run_check_b(config_info)
        results["Check B (Real Provider)"] = "PASS" if ok_b else "FAIL"
        log_step(results["Check B (Real Provider)"], "Check B", "Real Ollama Provider Communication")

        if not ok_b or provider is None:
            log_header("Verification Summary: FAILED at Check B")
            return 1

        # Check C: Actual LLM Planning
        try:
            ok_c = run_check_c(provider)
            results["Check C (LLM Planning)"] = "PASS" if ok_c else "FAIL"
        except Exception as e:
            print(f"  [ERROR] Check C failed with unexpected exception: {e}")
            ok_c = False
            results["Check C (LLM Planning)"] = "FAIL"

        log_step(results["Check C (LLM Planning)"], "Check C", "Actual LLM Planning (Real Ollama, No Fallback)")

        if not ok_c:
            log_header("Verification Summary: FAILED at Check C")
            return 1
    finally:
        if provider is not None:
            provider.close()

    # Check D: Orchestrator Configuration
    ok_d = run_check_d()
    results["Check D (Orchestrator)"] = "PASS" if ok_d else "FAIL"
    log_step(results["Check D (Orchestrator)"], "Check D", "AgentOrchestrator Strategy Selection")

    if not ok_d:
        log_header("Verification Summary: FAILED at Check D")
        return 1

    # Final Verification Summary & Exit Code
    log_header("Live Integration Verification Summary")
    all_passed = True
    for check_name, status in results.items():
        log_step(status, check_name, "Verified")
        if status != "PASS":
            all_passed = False

    if all_passed:
        print("\n\033[92mALL 4 REQUIRED INTEGRATION CHECKS PASSED SUCCESSFULLY!\033[0m")
        print("Smart Enroll successfully orchestrates planning via local Ollama (qwen2.5:3b).")
        return 0
    else:
        print("\n\033[91mONE OR MORE INTEGRATION CHECKS FAILED.\033[0m")
        return 1


if __name__ == "__main__":
    sys.exit(main())
