"""
Smart Enroll — Real Ollama LLM Live Integration Tests

Tests real HTTP communication with local Ollama daemon and verifies
that LLMPlanningStrategy successfully plans actions without fallback.

ISOLATION & SAFETY REQUIREMENTS:
- Strict opt-in requirement: Live network calls to Ollama are NEVER made unless
  the environment variable `SMART_ENROLL_RUN_LIVE_LLM_TESTS=1` is explicitly set.
- Without this variable, all tests in this module skip cleanly with a clear explanation.
- Endpoint safety: Strictly validates recognized local loopback and port before making requests.
- No live tests ever run against real development data or production credentials.
"""

import json
import os
import urllib.parse
import httpx
import pytest

from app.agents.llm_planner import LLMPlanningStrategy
from app.agents.orchestrator import ApplicationObservation, PlannedAction
from app.agents.providers import (
    LLMSSRFValidationError,
    OpenAICompatibleProvider,
    is_local_endpoint,
    validate_endpoint_url,
)
from app.core.config import settings
from app.schemas.agent import OrchestrationOutcome, ToolName, WorkflowStage

ENV_OPT_IN_VAR = "SMART_ENROLL_RUN_LIVE_LLM_TESTS"


def is_live_llm_opted_in() -> bool:
    """Check whether caller explicitly opted in to live LLM network tests."""
    return os.environ.get(ENV_OPT_IN_VAR) == "1"


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


# Evaluate configuration safety
_is_opted_in = is_live_llm_opted_in()
_is_safe_ollama, _ollama_safety_reason = validate_local_ollama_endpoint(
    endpoint_url=settings.LLM_API_BASE,
    provider_name=settings.LLM_PROVIDER,
    allow_local_endpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
)


def _is_local_ollama_reachable() -> bool:
    """
    Only probe network if explicitly opted in AND verified safe local Ollama endpoint.
    Never probes network when opt-in is disabled or endpoint is remote.
    """
    if not _is_opted_in or not _is_safe_ollama:
        return False
    try:
        parsed = urllib.parse.urlparse(settings.LLM_API_BASE)
        probe_url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
        r = httpx.get(probe_url, timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


# Pytest markers for clean skipping
skip_if_not_opted_in = pytest.mark.skipif(
    not _is_opted_in,
    reason=f"Live Ollama tests require explicit opt-in via {ENV_OPT_IN_VAR}=1",
)

skip_if_not_safe_ollama = pytest.mark.skipif(
    _is_opted_in and not _is_safe_ollama,
    reason=f"Configured endpoint is not safe for local Ollama: {_ollama_safety_reason}",
)

skip_if_ollama_unreachable = pytest.mark.skipif(
    _is_opted_in and _is_safe_ollama and not _is_local_ollama_reachable(),
    reason=f"Local Ollama daemon at {sanitize_url_for_display(settings.LLM_API_BASE)} is unreachable despite opt-in",
)


@pytest.fixture
def live_ollama_provider():
    """
    Fixture providing OpenAICompatibleProvider for local Ollama with guaranteed cleanup.
    """
    is_safe, reason = validate_local_ollama_endpoint(
        endpoint_url=settings.LLM_API_BASE,
        provider_name=settings.LLM_PROVIDER,
        allow_local_endpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
    )
    assert is_safe, f"Refusing to create provider: {reason}"

    provider = OpenAICompatibleProvider(
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        api_base=settings.LLM_API_BASE,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        temperature=settings.LLM_TEMPERATURE,
        allow_local_endpoints=settings.LLM_ALLOW_LOCAL_ENDPOINTS,
    )
    try:
        yield provider
    finally:
        provider.close()


@skip_if_not_opted_in
@skip_if_not_safe_ollama
@skip_if_ollama_unreachable
def test_live_ollama_provider_communication(live_ollama_provider):
    """
    Verify real HTTP communication with local Ollama through OpenAICompatibleProvider.
    Uses application settings without hardcoding secrets or bypassing SSRF rules.
    Guarantees provider cleanup even if assertions fail.
    """
    raw = live_ollama_provider.generate_plan_proposal(
        system_prompt='You are a test assistant. Reply strictly in JSON: {"status": "ok"}',
        user_prompt="ping",
    )
    data = json.loads(raw)
    assert isinstance(data, dict), f"Expected JSON object, got {type(data).__name__}"
    assert data.get("status") == "ok", f"Expected status 'ok', got '{data.get('status')}'"


@skip_if_not_opted_in
@skip_if_not_safe_ollama
@skip_if_ollama_unreachable
def test_live_ollama_planning_without_fallback(live_ollama_provider):
    """
    Verify that real local Ollama processes a planning proposal through LLMPlanningStrategy
    and satisfies domain guardrails with fallback strictly disabled.
    Guarantees provider cleanup even if assertions fail.
    """
    strategy = LLMPlanningStrategy(
        provider=live_ollama_provider,
        fallback_enabled=False,
    )

    live_doc = {
        "documentId": "doc-live-ocr-1",
        "documentType": "10TH_MARKSHEET",
        "status": "UPLOADED",
        "processingStatus": "PENDING",
    }
    obs = ApplicationObservation(
        application_id="app-live-verify-1",
        current_status="PROCESSING",
        programme_id="mca",
        applicant_id="app-user-1",
        user_id="user_123",
        applicant_name="Synthetic Candidate",
        is_document_complete=True,
        missing_document_types=[],
        uploaded_documents=[live_doc],
        unprocessed_documents=[live_doc],
        failed_documents=[],
        mismatched_documents=[],
        manual_review_documents=[],
        validated_documents=[],
        eligibility_result=None,
    )

    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    assert action is not None, "PlannedAction must not be None"
    assert isinstance(action, PlannedAction), f"Expected PlannedAction instance, got {type(action)}"
    assert action.tool == ToolName.PROCESS_DOCUMENT
    assert action.parameters.get("document_id") == "doc-live-ocr-1"
    assert action.stage == WorkflowStage.ACT
    assert action.is_terminal is False
    assert action.terminal_outcome is None
    assert outcome is None
    assert outcome != OrchestrationOutcome.FAILED
    assert rationale is not None and len(rationale) > 0
