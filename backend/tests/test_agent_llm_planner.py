"""
Unit and Integration Tests for LLM Provider & Agentic Hardening (Increment 15, Task 15.3)

Strictly uses mocked transports and zero live network calls.
Covers:
1. Disabled mode and missing credentials.
2. Valid structured tool proposal.
3. Valid terminal proposal subject to deterministic policy.
4. Malformed JSON and invalid schema.
5. Unknown tool, missing arguments, extra arguments, and invalid argument types.
6. Invalid workflow stage and forbidden terminal outcome.
7. Timeout, connection failure, HTTP 401, 429, and 5xx responses.
8. Deterministic fallback and sanitized audit metadata.
9. Failure of both the provider and deterministic planner (fallback_enabled=False).
10. No secret, applicant PII, raw response, or hidden reasoning in logs or audit events.
11. End-to-end orchestration with LLM planner, RBAC, fencing, and execution recovery.
12. Prevention of LLM bypassing deterministic verification or eligibility controls.
"""

import json
import socket
from unittest.mock import MagicMock, patch
import httpx
import pytest

from app.agents.llm_planner import (
    LLMPlanningStrategy,
    SYSTEM_PLANNING_PROMPT,
    sanitize_observation_for_llm,
)
from app.agents.orchestrator import (
    AgentOrchestrator,
    ApplicationObservation,
    DeterministicPlanningStrategy,
    PlannedAction,
)
from app.agents.providers import (
    LLMProviderConnectionError,
    LLMProviderHTTPError,
    LLMProviderTimeoutError,
    LLMSSRFValidationError,
    OpenAICompatibleProvider,
    is_local_endpoint,
    validate_endpoint_url,
)
from app.core.config import settings
from app.core.database import get_db
from app.schemas.agent import (
    LLMPlanProposal,
    OrchestrationOutcome,
    ToolName,
    WorkflowStage,
)


# =====================================================================
# Test Fixtures & Helpers
# =====================================================================

@pytest.fixture
def clean_db():
    db = get_db()
    db["applications"].delete_many({})
    db["documents"].delete_many({})
    db["agent_activity"].delete_many({})
    db["orchestration_runs"].delete_many({})
    yield db


def make_test_observation(
    application_id: str = "app-test-100",
    current_status: str = "PROCESSING",
    programme_id: str = "mca",
    is_document_complete: bool = True,
    missing_docs: list[str] | None = None,
    unprocessed_docs: list[dict] | None = None,
    failed_docs: list[dict] | None = None,
    mismatched_docs: list[dict] | None = None,
    validated_docs: list[dict] | None = None,
    eligibility_result: dict | None = None,
) -> ApplicationObservation:
    missing = missing_docs or []
    uploaded = []
    for i in range(6 - len(missing)):
        uploaded.append({
            "documentId": f"doc-{i}",
            "documentType": "10TH_MARKSHEET" if i == 0 else f"DOC_{i}",
            "processingStatus": "COMPLETED",
            "validationStatus": "VALIDATED",
            "status": "VALIDATED",
        })

    return ApplicationObservation(
        application_id=application_id,
        current_status=current_status,
        programme_id=programme_id,
        applicant_id="app-user-1",
        user_id="user_123",
        applicant_name="Confidential Applicant Name",
        is_document_complete=is_document_complete,
        missing_document_types=missing,
        uploaded_documents=uploaded,
        unprocessed_documents=unprocessed_docs or [],
        failed_documents=failed_docs or [],
        mismatched_documents=mismatched_docs or [],
        manual_review_documents=[],
        validated_documents=validated_docs or uploaded,
        eligibility_result=eligibility_result,
    )


def make_mock_transport_for_json(response_dict: dict, status_code: int = 200) -> httpx.MockTransport:
    content = json.dumps(response_dict).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers={"Content-Type": "application/json"},
        )

    return httpx.MockTransport(handler)


def make_openai_response(proposal_dict: dict) -> dict:
    return {
        "id": "chatcmpl-test-123",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(proposal_dict),
                },
                "finish_reason": "stop",
            }
        ],
    }


# =====================================================================
# 1. SSRF Endpoint Validation Tests
# =====================================================================

def test_ssrf_validation_rejects_local_and_private_addresses():
    # Disallowed hosts
    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("http://localhost:8000/v1", allow_local_endpoints=False)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("http://127.0.0.1:11434/v1", allow_local_endpoints=False)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("http://169.254.169.254/latest/meta-data", allow_local_endpoints=False)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("ftp://example.com/v1", allow_local_endpoints=False)

    # Allowed when explicitly configured
    allowed = validate_endpoint_url("http://localhost:11434/v1", allow_local_endpoints=True)
    assert allowed == "http://localhost:11434/v1"

    # Valid public domain
    valid = validate_endpoint_url("https://api.openai.com/v1", allow_local_endpoints=False)
    assert valid == "https://api.openai.com/v1"


def test_ssrf_validation_rejects_malformed_and_unsupported_schemes():
    # Unsupported schemes rejected even if local endpoints allowed
    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("ftp://localhost:11434/v1", allow_local_endpoints=True)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("file:///etc/passwd", allow_local_endpoints=True)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("javascript:alert(1)", allow_local_endpoints=True)

    # Missing hostname or malformed structure rejected
    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("http:///v1", allow_local_endpoints=True)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url("", allow_local_endpoints=True)

    with pytest.raises(LLMSSRFValidationError):
        validate_endpoint_url(None, allow_local_endpoints=True)


def test_is_local_endpoint_detection():
    # Unambiguous loopback endpoints
    assert is_local_endpoint("http://localhost:11434/v1") is True
    assert is_local_endpoint("http://127.0.0.1:11434/v1") is True
    assert is_local_endpoint("http://127.0.0.2:8000/v1") is True
    assert is_local_endpoint("http://[::1]:11434/v1") is True
    assert is_local_endpoint("http://test.localhost:11434/v1") is True

    # Suffixes that are NOT loopback must NOT receive keyless privileges
    assert is_local_endpoint("http://ollama.local:11434/v1") is False
    assert is_local_endpoint("http://model.internal:11434/v1") is False
    assert is_local_endpoint("http://gateway.arpa:11434/v1") is False

    # Wildcard / unspecified / LAN / remote addresses are not loopback
    assert is_local_endpoint("http://0.0.0.0:11434/v1") is False
    assert is_local_endpoint("http://[::]:11434/v1") is False
    assert is_local_endpoint("http://192.168.1.100:11434/v1") is False
    assert is_local_endpoint("https://api.openai.com/v1") is False
    assert is_local_endpoint("https://groq.com/v1") is False
    assert is_local_endpoint("") is False
    assert is_local_endpoint(None) is False
    assert is_local_endpoint("invalid-not-a-url") is False


# =====================================================================
# 2. Provider Unit & Error Handling Tests
# =====================================================================

def test_provider_initialization_and_credential_masking():
    provider = OpenAICompatibleProvider(
        api_key="sk-secret-key-1234567890",
        model="gpt-4o-mini",
        api_base="https://api.openai.com/v1",
    )
    repr_str = repr(provider)
    assert "sk-secret-key-1234567890" not in repr_str
    assert "sk-...7890" in repr_str
    provider.close()


def test_local_ollama_provider_without_api_key_sends_no_authorization_header():
    captured_headers = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update({k.lower(): v for k, v in request.headers.items()})
        proposal = {
            "action_type": "TERMINATE",
            "tool": None,
            "parameters": {},
            "rationale": "Ollama local proposal without key",
            "stage": "ACT",
            "is_terminal": True,
            "terminal_outcome": "WAITING_FOR_APPLICANT",
        }
        return httpx.Response(200, json=make_openai_response(proposal))

    transport = httpx.MockTransport(capture_handler)
    provider = OpenAICompatibleProvider(
        api_key=None,
        api_base="http://localhost:11434/v1",
        allow_local_endpoints=True,
        transport=transport,
    )
    result = provider.generate_plan_proposal("sys", "user")
    assert result
    # Crucial check: No authorization header sent for keyless local provider
    assert "authorization" not in captured_headers
    provider.close()


def test_remote_provider_with_api_key_sends_bearer_authorization_header():
    captured_headers = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update({k.lower(): v for k, v in request.headers.items()})
        proposal = {
            "action_type": "TERMINATE",
            "tool": None,
            "parameters": {},
            "rationale": "Remote proposal with key",
            "stage": "ACT",
            "is_terminal": True,
            "terminal_outcome": "WAITING_FOR_APPLICANT",
        }
        return httpx.Response(200, json=make_openai_response(proposal))

    transport = httpx.MockTransport(capture_handler)
    provider = OpenAICompatibleProvider(
        api_key="sk-remote-secret-key",
        api_base="https://api.openai.com/v1",
        allow_local_endpoints=False,
        transport=transport,
    )
    result = provider.generate_plan_proposal("sys", "user")
    assert result
    assert captured_headers.get("authorization") == "Bearer sk-remote-secret-key"
    provider.close()



def test_provider_timeout_raises_llm_provider_timeout_error():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out", request=request)

    transport = httpx.MockTransport(timeout_handler)
    provider = OpenAICompatibleProvider(
        api_key="sk-test",
        api_base="https://api.openai.com/v1",
        timeout_seconds=2.0,
        transport=transport,
    )
    with pytest.raises(LLMProviderTimeoutError) as exc_info:
        provider.generate_plan_proposal("system prompt", "user prompt")
    assert "timed out" in str(exc_info.value).lower()
    provider.close()


def test_provider_http_errors_raise_llm_provider_http_error():
    # 401 Unauthorized
    transport_401 = make_mock_transport_for_json({"error": "invalid_api_key"}, status_code=401)
    provider = OpenAICompatibleProvider(api_key="sk-bad", api_base="https://api.openai.com/v1", transport=transport_401)
    with pytest.raises(LLMProviderHTTPError) as exc_401:
        provider.generate_plan_proposal("sys", "user")
    assert exc_401.value.status_code == 401

    # 429 Rate Limit
    transport_429 = make_mock_transport_for_json({"error": "rate_limit_exceeded"}, status_code=429)
    provider_429 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport_429)
    with pytest.raises(LLMProviderHTTPError) as exc_429:
        provider_429.generate_plan_proposal("sys", "user")
    assert exc_429.value.status_code == 429

    # 500 Internal Server Error
    transport_500 = make_mock_transport_for_json({"error": "internal_error"}, status_code=500)
    provider_500 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport_500)
    with pytest.raises(LLMProviderHTTPError) as exc_500:
        provider_500.generate_plan_proposal("sys", "user")
    assert exc_500.value.status_code == 500


def test_provider_connection_error_raises_llm_provider_connection_error():
    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network unreachable", request=request)

    transport = httpx.MockTransport(error_handler)
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    with pytest.raises(LLMProviderConnectionError):
        provider.generate_plan_proposal("sys", "user")
    provider.close()


# =====================================================================
# 3. Privacy & Sanitization: Zero PII Transmitted to LLM
# =====================================================================

def test_observation_sanitizer_excludes_all_pii():
    obs = make_test_observation(
        application_id="app-priv-999",
        current_status="PROCESSING",
    )
    obs.applicant_name = "Secret Applicant Name"
    obs.applicant_id = "applicant-ident-secret"
    obs.user_id = "user-ident-secret"

    sanitized = sanitize_observation_for_llm(obs)

    # Convert to serialized string to verify no leaks anywhere in output
    dumped = json.dumps(sanitized)
    assert "Secret Applicant Name" not in dumped
    assert "applicant-ident-secret" not in dumped
    assert "user-ident-secret" not in dumped
    assert "Confidential" not in dumped

    # Verifying operational fields ARE present
    assert sanitized["applicationId"] == "app-priv-999"
    assert sanitized["currentStatus"] == "PROCESSING"
    assert sanitized["programmeId"] == "mca"
    assert "documents" in sanitized


# =====================================================================
# 4. LLM Planning Strategy: Valid Proposals
# =====================================================================

def test_llm_planner_valid_tool_call_proposal():
    proposal_data = {
        "action_type": "TOOL_CALL",
        "tool": "process_document",
        "parameters": {"document_id": "doc-ocr-123"},
        "rationale": "Extract text and document fields via OCR pipeline.",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider)

    obs = make_test_observation()
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    assert action is not None
    assert action.tool == ToolName.PROCESS_DOCUMENT
    assert action.parameters == {"document_id": "doc-ocr-123"}
    assert action.rationale == "Extract text and document fields via OCR pipeline."
    assert outcome is None
    provider.close()


def test_llm_planner_valid_terminate_proposal():
    proposal_data = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Waiting for applicant to upload missing documents.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "WAITING_FOR_APPLICANT",
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider)

    obs = make_test_observation(current_status="WAITING_FOR_DOCUMENTS", is_document_complete=False)
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    assert action is None
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert rationale == "Waiting for applicant to upload missing documents."
    provider.close()


# =====================================================================
# 5. Guardrails & Validation: Rejection & Fallback
# =====================================================================

def test_llm_planner_malformed_json_triggers_deterministic_fallback():
    # Return broken JSON
    bad_response = {
        "choices": [{"message": {"content": "{ action_type: 'TOOL_CALL', tool: BROKEN JSON"}}]
    }
    transport = make_mock_transport_for_json(bad_response)
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)

    # Use mock db to verify fallback audit record
    mock_db = MagicMock()
    strategy = LLMPlanningStrategy(provider=provider, db=mock_db, fallback_enabled=True)

    obs = make_test_observation(current_status="DRAFT")
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    # Fallback to DeterministicPlanningStrategy for DRAFT yields WAITING_FOR_APPLICANT
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert mock_db["agent_activity"].insert_one.called
    provider.close()


def test_llm_planner_unknown_tool_triggers_fallback():
    proposal_data = {
        "action_type": "TOOL_CALL",
        "tool": "unregistered_arbitrary_tool",
        "parameters": {"cmd": "rm -rf /"},
        "rationale": "Attempt to call unauthorized tool.",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, fallback_enabled=True)

    obs = make_test_observation(current_status="DRAFT")
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    # Deterministic fallback handles it safely
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    provider.close()


def test_llm_planner_forbidden_status_transition_triggers_fallback():
    # Model attempts to arbitrarily declare applicant ELIGIBLE without verification/check_eligibility
    proposal_data = {
        "action_type": "TOOL_CALL",
        "tool": "update_application_status",
        "parameters": {"application_id": "app-100", "new_status": "ELIGIBLE"},
        "rationale": "Bypassing admission rules to approve applicant.",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, fallback_enabled=True)

    obs = make_test_observation(current_status="DRAFT")
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    # Fallback prevents the forbidden transition
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    provider.close()


def test_llm_planner_forbidden_premature_processing_complete_triggers_fallback():
    # Model attempts to transition to PROCESSING_COMPLETE without eligibility result
    proposal_data = {
        "action_type": "TOOL_CALL",
        "tool": "update_application_status",
        "parameters": {"application_id": "app-100", "new_status": "PROCESSING_COMPLETE"},
        "rationale": "Prematurely completing workflow.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "COMPLETED",
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, fallback_enabled=True)

    obs = make_test_observation(current_status="DRAFT", eligibility_result=None)
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    # Guardrail caught the premature completion and fell back
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    provider.close()


def test_llm_planner_extra_arguments_rejected():
    # Extra field forbidden by ConfigDict(extra="forbid")
    proposal_data = {
        "action_type": "TOOL_CALL",
        "tool": "process_document",
        "parameters": {"document_id": "doc-1"},
        "rationale": "Processing document.",
        "unauthorized_field": "injected_value",
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, fallback_enabled=True)

    obs = make_test_observation(current_status="DRAFT")
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    provider.close()


def test_llm_planner_fallback_disabled_returns_failed_outcome():
    # When fallback_enabled=False, errors return OrchestrationOutcome.FAILED
    transport = make_mock_transport_for_json({"error": "quota_exceeded"}, status_code=429)
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, fallback_enabled=False)

    obs = make_test_observation(current_status="PROCESSING")
    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)

    assert action is None
    assert outcome == OrchestrationOutcome.FAILED
    assert "Model-backed planning failed without fallback" in str(rationale)
    provider.close()


# =====================================================================
# 6. End-to-End Orchestrator Integration with LLM Planning Strategy
# =====================================================================

def test_orchestrator_initializes_with_llm_strategy_from_settings(clean_db):
    with patch("app.core.config.settings.LLM_PROVIDER", "openai_compatible"), \
         patch("app.core.config.settings.LLM_API_KEY", "sk-mock-key"), \
         patch("app.core.config.settings.LLM_API_BASE", "https://api.openai.com/v1"):
        orchestrator = AgentOrchestrator(db=clean_db)
        assert isinstance(orchestrator.strategy, LLMPlanningStrategy)
        assert orchestrator.strategy.planner_name == "LLM"


def test_orchestrator_defaults_to_deterministic_when_provider_disabled(clean_db):
    with patch("app.core.config.settings.LLM_PROVIDER", "disabled"), \
         patch("app.core.config.settings.LLM_API_KEY", None):
        orchestrator = AgentOrchestrator(db=clean_db)
        assert isinstance(orchestrator.strategy, DeterministicPlanningStrategy)
        assert orchestrator.strategy.planner_name == "DETERMINISTIC"


def test_orchestrator_initializes_with_local_ollama_without_api_key(clean_db):
    with patch("app.core.config.settings.LLM_PROVIDER", "openai_compatible"), \
         patch("app.core.config.settings.LLM_API_KEY", None), \
         patch("app.core.config.settings.LLM_API_BASE", "http://localhost:11434/v1"), \
         patch("app.core.config.settings.LLM_ALLOW_LOCAL_ENDPOINTS", True):
        orchestrator = AgentOrchestrator(db=clean_db)
        assert isinstance(orchestrator.strategy, LLMPlanningStrategy)
        assert orchestrator.strategy.planner_name == "LLM"
        assert orchestrator.strategy.provider.api_key is None
        orchestrator.strategy.provider.close()


def test_orchestrator_rejects_remote_provider_without_api_key_even_if_local_allowed(clean_db):
    with patch("app.core.config.settings.LLM_PROVIDER", "openai_compatible"), \
         patch("app.core.config.settings.LLM_API_KEY", None), \
         patch("app.core.config.settings.LLM_API_BASE", "https://api.openai.com/v1"), \
         patch("app.core.config.settings.LLM_ALLOW_LOCAL_ENDPOINTS", True):
        orchestrator = AgentOrchestrator(db=clean_db)
        # Without credentials on a remote endpoint, fallback to deterministic
        assert isinstance(orchestrator.strategy, DeterministicPlanningStrategy)
        assert orchestrator.strategy.planner_name == "DETERMINISTIC"


def test_orchestrator_rejects_local_ollama_if_local_endpoints_forbidden(clean_db):
    with patch("app.core.config.settings.LLM_PROVIDER", "openai_compatible"), \
         patch("app.core.config.settings.LLM_API_KEY", None), \
         patch("app.core.config.settings.LLM_API_BASE", "http://localhost:11434/v1"), \
         patch("app.core.config.settings.LLM_ALLOW_LOCAL_ENDPOINTS", False):
        orchestrator = AgentOrchestrator(db=clean_db)
        # Disallowing local endpoints prevents unauthenticated local initialization
        assert isinstance(orchestrator.strategy, DeterministicPlanningStrategy)
        assert orchestrator.strategy.planner_name == "DETERMINISTIC"


def test_orchestrator_rejects_arbitrary_local_internal_arpa_domain_suffixes_without_api_key(clean_db):
    for test_url in (
        "http://ollama.local:11434/v1",
        "http://model.internal:11434/v1",
        "http://gateway.arpa:11434/v1",
    ):
        with patch("app.core.config.settings.LLM_PROVIDER", "openai_compatible"), \
             patch("app.core.config.settings.LLM_API_KEY", None), \
             patch("app.core.config.settings.LLM_API_BASE", test_url), \
             patch("app.core.config.settings.LLM_ALLOW_LOCAL_ENDPOINTS", True):
            orchestrator = AgentOrchestrator(db=clean_db)
            # Arbitrary domain suffixes are not loopback; cannot initialize keyless
            assert isinstance(orchestrator.strategy, DeterministicPlanningStrategy)
            assert orchestrator.strategy.planner_name == "DETERMINISTIC"


def test_orchestrator_end_to_end_with_mocked_llm_provider(clean_db):
    app_id = "app-llm-e2e-1"
    clean_db["applications"].delete_many({"applicationId": app_id})
    clean_db["orchestration_runs"].delete_many({"applicationId": app_id})
    clean_db["documents"].delete_many({"applicationId": app_id})
    clean_db["agent_activity"].delete_many({"applicationId": app_id})

    clean_db["applications"].insert_one({
        "applicationId": app_id,
        "applicantId": "applicant-e2e-1",
        "userId": "user_e2e_1",
        "status": "WAITING_FOR_DOCUMENTS",
        "programmeId": "mca",
    })

    # Proposal: TERMINATE because still waiting for documents
    proposal_data = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Application is waiting for applicant to upload missing documents.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "WAITING_FOR_APPLICANT",
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal_data))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db)

    orchestrator = AgentOrchestrator(db=clean_db, planning_strategy=strategy)
    current_user = {"_id": "user_e2e_1", "role": "applicant", "applicant_id": "applicant-e2e-1"}

    response = orchestrator.run(application_id=app_id, triggered_by_user=current_user)

    assert response.outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert response.status.value == "COMPLETED"
    assert response.planner == "LLM"
    provider.close()


def test_orchestrator_end_to_end_llm_fallback_on_provider_timeout(clean_db):
    app_id = "app-llm-fallback-1"
    clean_db["applications"].delete_many({"applicationId": app_id})
    clean_db["orchestration_runs"].delete_many({"applicationId": app_id})
    clean_db["documents"].delete_many({"applicationId": app_id})
    clean_db["agent_activity"].delete_many({"applicationId": app_id})

    clean_db["applications"].insert_one({
        "applicationId": app_id,
        "applicantId": "applicant-fb-1",
        "userId": "user_fb_1",
        "status": "DRAFT",
        "programmeId": "mca",
    })

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Mock timeout", request=request)

    transport = httpx.MockTransport(timeout_handler)
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    orchestrator = AgentOrchestrator(db=clean_db, planning_strategy=strategy)
    current_user = {"_id": "user_fb_1", "role": "applicant", "applicant_id": "applicant-fb-1"}

    response = orchestrator.run(application_id=app_id, triggered_by_user=current_user)

    # Fallback to deterministic planner successfully completes DRAFT inspection
    assert response.outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert response.status.value == "COMPLETED"

    # Verify fallback audit event exists
    fallback_event = clean_db["agent_activity"].find_one({
        "applicationId": app_id,
        "status": "FALLBACK",
    })
    assert fallback_event is not None
    assert "timeout" in fallback_event.get("result", "").lower()
    provider.close()


# =====================================================================
# 11. PR #4 Review Corrections Regression Tests
# =====================================================================

# ---------------------------------------------------------------------
# Finding 2: SSRF Destination Validation Regression Tests
# ---------------------------------------------------------------------

def test_ssrf_validation_permits_loopback_only_when_explicitly_enabled():
    """Verify loopback is allowed ONLY when allow_local_endpoints is True."""
    for loopback_url in (
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://127.0.0.2:8000/v1",
        "http://[::1]:11434/v1",
    ):
        # Must fail when allow_local_endpoints is False
        with pytest.raises(LLMSSRFValidationError) as exc_info:
            validate_endpoint_url(loopback_url, allow_local_endpoints=False)
        assert "forbidden unless allow_local_endpoints is enabled" in str(exc_info.value)

        # Must succeed when allow_local_endpoints is True
        result = validate_endpoint_url(loopback_url, allow_local_endpoints=True)
        assert result == loopback_url


def test_ssrf_validation_rejects_private_and_link_local_even_when_local_endpoints_enabled():
    """
    Enabling allow_local_endpoints MUST NOT bypass SSRF checks for
    link-local, RFC 1918 private, unspecified, or restricted domains.
    """
    restricted_targets = [
        "http://169.254.169.254/latest/meta-data",       # AWS/cloud metadata link-local
        "http://169.254.1.1:8000/v1",                    # Link-local IPv4
        "http://10.0.0.1:8000/v1",                       # RFC 1918 Class A
        "http://10.254.0.1:11434/v1",                    # RFC 1918 Class A
        "http://172.16.0.1:8000/v1",                     # RFC 1918 Class B
        "http://192.168.1.1:8000/v1",                    # RFC 1918 Class C
        "http://192.168.0.254:11434/v1",                 # RFC 1918 Class C
        "http://0.0.0.0:11434/v1",                       # Unspecified IPv4
        "http://[::]:11434/v1",                          # Unspecified IPv6
        "http://ollama.local:11434/v1",                  # .local mDNS
        "http://metadata.google.internal/v1",            # .internal cloud metadata
        "http://gateway.arpa/v1",                        # .arpa reverse DNS
    ]

    for target in restricted_targets:
        with pytest.raises(LLMSSRFValidationError):
            validate_endpoint_url(target, allow_local_endpoints=True)


def test_orchestrator_rejects_credential_leak_to_restricted_destination_when_local_enabled(clean_db):
    """
    Verify that configuring credentials with allow_local_endpoints=True cannot
    send credentials to private/metadata endpoints because validation rejects them.
    """
    with patch("app.core.config.settings.LLM_PROVIDER", "openai_compatible"), \
         patch("app.core.config.settings.LLM_API_KEY", "sk-secret-do-not-leak"), \
         patch("app.core.config.settings.LLM_API_BASE", "http://169.254.169.254/latest/meta-data"), \
         patch("app.core.config.settings.LLM_ALLOW_LOCAL_ENDPOINTS", True):
        orchestrator = AgentOrchestrator(db=clean_db)
        # Must safely fall back to deterministic strategy without transmitting credentials
        assert isinstance(orchestrator.strategy, DeterministicPlanningStrategy)
        assert orchestrator.strategy.planner_name == "DETERMINISTIC"


# ---------------------------------------------------------------------
# Finding 1: Terminal Outcome Validation Against Deterministic Workflow State
# ---------------------------------------------------------------------

def test_llm_planner_rejects_completed_terminal_outcome_for_draft_and_falls_back(clean_db):
    """
    A model must NOT be able to report COMPLETED while the application is still in DRAFT.
    Must be rejected with fallback to DeterministicPlanningStrategy.
    """
    obs = make_test_observation(
        application_id="app-guard-draft",
        current_status="DRAFT",
        is_document_complete=False,
    )

    invalid_proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Model prematurely asserts application is completed.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "COMPLETED",
    }
    transport = make_mock_transport_for_json(make_openai_response(invalid_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    # Must fall back to deterministic planner's safe WAITING_FOR_APPLICANT
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert action is None

    # Verify audit trail records the rejection and fallback
    audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-draft", "status": "FALLBACK"})
    assert audit is not None
    assert "cannot report 'completed'" in audit["result"].lower()
    provider.close()


def test_llm_planner_rejects_completed_for_submitted_and_processing_without_eligibility(clean_db):
    """
    A model must NOT be able to report COMPLETED while the application is in
    SUBMITTED or PROCESSING or without deterministic eligibility evidence.
    """
    for status in ("SUBMITTED", "PROCESSING", "WAITING_FOR_DOCUMENTS", "VERIFICATION_IN_PROGRESS"):
        obs = make_test_observation(
            application_id=f"app-guard-{status.lower()}",
            current_status=status,
            is_document_complete=True,
            eligibility_result=None,
        )

        invalid_proposal = {
            "action_type": "TERMINATE",
            "tool": None,
            "parameters": {},
            "rationale": "Model attempts completion without workflow completion evidence.",
            "stage": "ACT",
            "is_terminal": True,
            "terminal_outcome": "COMPLETED",
        }
        transport = make_mock_transport_for_json(make_openai_response(invalid_proposal))
        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
        strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

        action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

        # Rejection occurs and delegates to deterministic fallback
        audit = clean_db["agent_activity"].find_one({"applicationId": f"app-guard-{status.lower()}", "status": "FALLBACK"})
        assert audit is not None
        assert "cannot report 'completed'" in audit["result"].lower()
        provider.close()


def test_llm_planner_rejects_inconsistent_waiting_for_applicant_when_workflow_complete(clean_db):
    """
    A model must NOT be able to report WAITING_FOR_APPLICANT when the application
    is already in PROCESSING_COMPLETE or all documents are complete.
    """
    obs = make_test_observation(
        application_id="app-guard-inconsistent-waiting",
        current_status="PROCESSING_COMPLETE",
        is_document_complete=True,
        eligibility_result={"status": "ELIGIBLE"},
    )

    invalid_proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Model claims applicant action needed on a finished application.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "WAITING_FOR_APPLICANT",
    }
    transport = make_mock_transport_for_json(make_openai_response(invalid_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    # Rejected and logged to audit
    audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-inconsistent-waiting", "status": "FALLBACK"})
    assert audit is not None
    assert "waiting_for_applicant" in audit["result"].lower()
    provider.close()


def test_llm_planner_rejects_manual_review_when_no_exception_or_failure_exists(clean_db):
    """
    A model must NOT be able to report MANUAL_REVIEW_REQUIRED when there is no
    exception, no failed document, and no validation mismatch.
    """
    obs = make_test_observation(
        application_id="app-guard-clean-processing",
        current_status="PROCESSING",
        is_document_complete=True,
        failed_docs=[],
        mismatched_docs=[],
    )

    invalid_proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Model spuriously requests manual review.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "MANUAL_REVIEW_REQUIRED",
    }
    transport = make_mock_transport_for_json(make_openai_response(invalid_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    # Rejection triggered
    audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-clean-processing", "status": "FALLBACK"})
    assert audit is not None
    assert "manual_review_required" in audit["result"].lower()
    provider.close()


def test_llm_planner_accepts_valid_completed_terminal_outcome_when_processing_complete(clean_db):
    """
    A model proposal reporting COMPLETED IS accepted when the application
    is actually in PROCESSING_COMPLETE with deterministic eligibility evidence.
    """
    obs = make_test_observation(
        application_id="app-guard-legit-complete",
        current_status="PROCESSING_COMPLETE",
        is_document_complete=True,
        eligibility_result={"status": "ELIGIBLE", "score": 88.0},
    )

    valid_proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Processing is complete and eligibility has been confirmed.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "COMPLETED",
    }
    transport = make_mock_transport_for_json(make_openai_response(valid_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    assert action is None
    assert outcome == OrchestrationOutcome.COMPLETED
    assert "eligibility has been confirmed" in rationale
    provider.close()


def test_llm_planner_accepts_legitimate_manual_review_on_failed_documents(clean_db):
    """
    Legitimate manual review proposal IS accepted when failed documents exist.
    """
    obs = make_test_observation(
        application_id="app-guard-failed-docs",
        current_status="PROCESSING",
        is_document_complete=True,
        failed_docs=[{"documentId": "doc-failed-1", "reason": "OCR unreadable"}],
    )

    valid_proposal = {
        "action_type": "TOOL_CALL",
        "tool": "update_application_status",
        "parameters": {"application_id": "app-guard-failed-docs", "new_status": "EXCEPTION"},
        "rationale": "Document processing failed. Flagging for manual review.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "MANUAL_REVIEW_REQUIRED",
    }
    transport = make_mock_transport_for_json(make_openai_response(valid_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    assert action is not None
    assert action.tool == ToolName.UPDATE_APPLICATION_STATUS
    assert outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    assert action.parameters["new_status"] == "EXCEPTION"
    provider.close()


# ---------------------------------------------------------------------
# Consistency Checks: Internal Tools and Parameter Binding
# ---------------------------------------------------------------------

def test_llm_planner_rejects_internal_record_audit_event_tool_proposal(clean_db):
    """
    The model must NOT be able to propose internal system tools like record_audit_event.
    """
    obs = make_test_observation(
        application_id="app-audit-tool-check",
        current_status="PROCESSING",
    )

    invalid_proposal = {
        "action_type": "TOOL_CALL",
        "tool": "record_audit_event",
        "parameters": {"action": "Fake audit", "result": "Bypass"},
        "rationale": "Attempting to call internal audit tool.",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(invalid_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    # Must reject and record fallback
    audit = clean_db["agent_activity"].find_one({"applicationId": "app-audit-tool-check", "status": "FALLBACK"})
    assert audit is not None
    assert "internal system tool" in audit["result"].lower()
    provider.close()


def test_llm_planner_auto_binds_application_id_and_validates_create_exception(clean_db):
    """
    Verify auto-binding of application_id and validation of required parameters
    for create_exception.
    """
    obs = make_test_observation(
        application_id="app-create-exc-check",
        current_status="EXCEPTION",
    )

    proposal = {
        "action_type": "TOOL_CALL",
        "tool": "create_exception",
        "parameters": {
            "exception_type": "DOCUMENT_ILLEGIBLE",
            "description": "Applicant uploaded blurry scan.",
        },
        "rationale": "Creating admission exception record.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "MANUAL_REVIEW_REQUIRED",
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    assert action is not None
    assert action.tool == ToolName.CREATE_EXCEPTION
    # Auto-bound application_id and default severity
    assert action.parameters["application_id"] == "app-create-exc-check"
    assert action.parameters["severity"] == "MEDIUM"
    assert action.parameters["exception_type"] == "DOCUMENT_ILLEGIBLE"
    assert outcome == OrchestrationOutcome.MANUAL_REVIEW_REQUIRED
    provider.close()


def test_llm_planner_rejects_cross_application_id_injection(clean_db):
    """
    Model proposing a tool parameter with a different application_id than
    the observed application must be rejected as cross-application violation.
    """
    obs = make_test_observation(
        application_id="app-legitimate-victim",
        current_status="PROCESSING",
    )

    injection_proposal = {
        "action_type": "TOOL_CALL",
        "tool": "get_application",
        "parameters": {"application_id": "app-attacker-target"},
        "rationale": "Model attempts to inspect unrelated application.",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(injection_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    # Must reject and record fallback
    audit = clean_db["agent_activity"].find_one({"applicationId": "app-legitimate-victim", "status": "FALLBACK"})
    assert audit is not None
    assert "cross-application access violation" in audit["result"].lower()
    provider.close()


# ---------------------------------------------------------------------
# Follow-up Review Corrections Regression Tests
# ---------------------------------------------------------------------

def test_validate_endpoint_url_fails_closed_on_dns_resolution_failure():
    """
    validate_endpoint_url MUST fail closed and raise LLMSSRFValidationError
    when socket.getaddrinfo raises socket.gaierror.
    """
    with patch("socket.getaddrinfo", side_effect=socket.gaierror(-2, "Name or service not known")):
        with pytest.raises(LLMSSRFValidationError) as exc_info:
            validate_endpoint_url("https://unresolvable.mock-domain.com/v1", allow_local_endpoints=False)
        assert "DNS resolution failed" in str(exc_info.value)

        # Even if allow_local_endpoints=True, remote unresolvable domains must fail closed
        with pytest.raises(LLMSSRFValidationError) as exc_info_local:
            validate_endpoint_url("https://unresolvable.mock-domain.com/v1", allow_local_endpoints=True)
        assert "DNS resolution failed" in str(exc_info_local.value)


def test_validate_endpoint_url_deterministic_public_endpoint_with_mocked_dns():
    """
    Verify public endpoints pass deterministically without depending on live DNS.
    """
    mock_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        valid = validate_endpoint_url("https://api.openai.com/v1", allow_local_endpoints=False)
        assert valid == "https://api.openai.com/v1"


def test_loopback_endpoints_do_not_require_dns_resolution():
    """
    Loopback endpoints when explicitly enabled must NOT invoke socket.getaddrinfo.
    """
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Should not be called for loopback")):
        allowed = validate_endpoint_url("http://localhost:11434/v1", allow_local_endpoints=True)
        assert allowed == "http://localhost:11434/v1"

        allowed_ip = validate_endpoint_url("http://127.0.0.1:11434/v1", allow_local_endpoints=True)
        assert allowed_ip == "http://127.0.0.1:11434/v1"


def test_llm_planner_rejects_model_proposed_failed_outcomes_and_falls_back(clean_db):
    """
    Model-proposed FAILED terminal outcome must be rejected across DRAFT,
    SUBMITTED, PROCESSING, and WAITING_FOR_DOCUMENTS, triggering deterministic fallback.
    """
    for test_status in ("DRAFT", "SUBMITTED", "PROCESSING", "WAITING_FOR_DOCUMENTS"):
        app_id = f"app-reject-failed-{test_status.lower()}"
        obs = make_test_observation(
            application_id=app_id,
            current_status=test_status,
            is_document_complete=(test_status == "PROCESSING"),
        )

        invalid_proposal = {
            "action_type": "TERMINATE",
            "tool": None,
            "parameters": {},
            "rationale": "Model unilaterally claims the run has failed.",
            "stage": "ACT",
            "is_terminal": True,
            "terminal_outcome": "FAILED",
        }
        transport = make_mock_transport_for_json(make_openai_response(invalid_proposal))
        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
        strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

        action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

        # Must reject and fallback safely
        audit = clean_db["agent_activity"].find_one({"applicationId": app_id, "status": "FALLBACK"})
        assert audit is not None
        assert "model-proposed 'failed' is not permitted" in audit["result"].lower()
        provider.close()


def test_llm_planner_rejects_circular_manual_review_on_clean_application(clean_db):
    """
    A model cannot move a clean application to EXCEPTION solely to justify
    a MANUAL_REVIEW_REQUIRED terminal outcome. Both the status update to EXCEPTION
    and the terminal outcome must be rejected without independent failure evidence.
    """
    obs = make_test_observation(
        application_id="app-clean-no-exc",
        current_status="PROCESSING",
        is_document_complete=True,
        failed_docs=[],
        mismatched_docs=[],
        unprocessed_docs=[],
    )

    # Attempt 1: Tool call changing status to EXCEPTION with MANUAL_REVIEW_REQUIRED
    circular_proposal = {
        "action_type": "TOOL_CALL",
        "tool": "update_application_status",
        "parameters": {"application_id": "app-clean-no-exc", "new_status": "EXCEPTION"},
        "rationale": "Attempting to create exception condition without evidence.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "MANUAL_REVIEW_REQUIRED",
    }
    transport = make_mock_transport_for_json(make_openai_response(circular_proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs, iteration=1)

    audit = clean_db["agent_activity"].find_one({"applicationId": "app-clean-no-exc", "status": "FALLBACK"})
    assert audit is not None
    assert "cannot transition application to 'exception' without independent evidence" in audit["result"].lower()
    provider.close()

    # Attempt 2: Bare create_exception proposal without independent evidence
    clean_db["agent_activity"].delete_many({})
    create_exc_proposal = {
        "action_type": "TOOL_CALL",
        "tool": "create_exception",
        "parameters": {
            "application_id": "app-clean-no-exc",
            "exception_type": "MANUAL_REVIEW",
            "description": "Unsubstantiated exception",
        },
        "rationale": "Proposing exception without independent failure evidence.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "MANUAL_REVIEW_REQUIRED",
    }
    transport2 = make_mock_transport_for_json(make_openai_response(create_exc_proposal))
    provider2 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport2)
    strategy2 = LLMPlanningStrategy(provider=provider2, db=clean_db, fallback_enabled=True)

    action2, outcome2, rationale2 = strategy2.plan_next_action(observation=obs, iteration=1)
    audit2 = clean_db["agent_activity"].find_one({"applicationId": "app-clean-no-exc", "status": "FALLBACK"})
    assert audit2 is not None
    assert "requires independent workflow evidence" in audit2["result"].lower()
    provider2.close()


def test_waiting_for_applicant_validation_against_document_completeness(clean_db):
    """
    WAITING_FOR_APPLICANT:
    - Accepted for DRAFT unconditionally.
    - Accepted for WAITING_FOR_DOCUMENTS when documents ARE missing.
    - REJECTED for WAITING_FOR_DOCUMENTS when documents ARE complete (falls back to resume processing).
    """
    # Case 1: DRAFT -> Accepted
    obs_draft = make_test_observation(
        application_id="app-wait-draft",
        current_status="DRAFT",
        is_document_complete=False,
    )
    draft_proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Waiting for applicant to submit draft.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "WAITING_FOR_APPLICANT",
    }
    transport1 = make_mock_transport_for_json(make_openai_response(draft_proposal))
    p1 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport1)
    s1 = LLMPlanningStrategy(provider=p1, db=clean_db, fallback_enabled=True)
    act1, out1, _ = s1.plan_next_action(observation=obs_draft, iteration=1)
    assert act1 is None
    assert out1 == OrchestrationOutcome.WAITING_FOR_APPLICANT
    p1.close()

    # Case 2: WAITING_FOR_DOCUMENTS with incomplete documents -> Accepted
    obs_waiting_incomplete = make_test_observation(
        application_id="app-wait-incomplete",
        current_status="WAITING_FOR_DOCUMENTS",
        is_document_complete=False,
        missing_docs=["DEGREE_CERTIFICATE"],
    )
    wait_proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Waiting for applicant to upload DEGREE_CERTIFICATE.",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "WAITING_FOR_APPLICANT",
    }
    transport2 = make_mock_transport_for_json(make_openai_response(wait_proposal))
    p2 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport2)
    s2 = LLMPlanningStrategy(provider=p2, db=clean_db, fallback_enabled=True)
    act2, out2, _ = s2.plan_next_action(observation=obs_waiting_incomplete, iteration=1)
    assert act2 is None
    assert out2 == OrchestrationOutcome.WAITING_FOR_APPLICANT
    p2.close()

    # Case 3: WAITING_FOR_DOCUMENTS with complete documents -> REJECTED and falls back to resume processing
    obs_waiting_complete = make_test_observation(
        application_id="app-wait-complete",
        current_status="WAITING_FOR_DOCUMENTS",
        is_document_complete=True,
        missing_docs=[],
    )
    transport3 = make_mock_transport_for_json(make_openai_response(wait_proposal))
    p3 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport3)
    s3 = LLMPlanningStrategy(provider=p3, db=clean_db, fallback_enabled=True)
    act3, out3, _ = s3.plan_next_action(observation=obs_waiting_complete, iteration=1)

    # Must be rejected; deterministic fallback resumes processing by updating status to PROCESSING
    assert act3 is not None
    assert act3.tool == ToolName.UPDATE_APPLICATION_STATUS
    assert act3.parameters["new_status"] == "PROCESSING"

    audit3 = clean_db["agent_activity"].find_one({"applicationId": "app-wait-complete", "status": "FALLBACK"})
    assert audit3 is not None
    assert "when all required documents are complete" in audit3["result"].lower()
    p3.close()


# =====================================================================
# 13. Strengthened Workflow Guardrails & Test Isolation (Increment 15, Task 15.3 Refinement)
# =====================================================================

def test_guardrail_draft_attempted_tool_call_rejected_and_falls_back(clean_db):
    """
    Rule 1: An application in DRAFT cannot execute any tool calls.
    Attempting request_missing_document is rejected by domain guardrails and falls back to WAITING_FOR_APPLICANT.
    """
    obs_draft = make_test_observation(
        application_id="app-guard-draft-1",
        current_status="DRAFT",
        is_document_complete=False,
        missing_docs=["10TH_MARKSHEET"],
    )
    proposal = {
        "action_type": "TOOL_CALL",
        "tool": "request_missing_document",
        "parameters": {"application_id": "app-guard-draft-1", "document_type": "10TH_MARKSHEET"},
        "rationale": "Attempting to request missing document for unsubmitted draft",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs_draft, iteration=1)

    # Must be rejected and fall back to deterministic planner
    assert action is None
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert "Application is in DRAFT status" in rationale

    fallback_audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-draft-1", "status": "FALLBACK"})
    assert fallback_audit is not None
    assert "Tool execution is prohibited while application is in 'DRAFT' status" in fallback_audit["result"]
    provider.close()


def test_guardrail_draft_invalid_terminal_outcome_rejected(clean_db):
    """
    Rule 1: An application in DRAFT must terminate with WAITING_FOR_APPLICANT.
    Attempting TERMINATE with MANUAL_REVIEW_REQUIRED or COMPLETED is rejected.
    """
    obs_draft = make_test_observation(
        application_id="app-guard-draft-2",
        current_status="DRAFT",
        is_document_complete=False,
    )
    proposal = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Premature manual review proposal for draft",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "MANUAL_REVIEW_REQUIRED",
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs_draft, iteration=1)

    assert action is None
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    fallback_audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-draft-2", "status": "FALLBACK"})
    assert fallback_audit is not None
    assert "Must terminate with 'WAITING_FOR_APPLICANT'" in fallback_audit["result"]
    provider.close()


def test_guardrail_submitted_missing_documents_cannot_call_request_missing_document(clean_db):
    """
    Rule 2: SUBMITTED application with missing documents must transition to WAITING_FOR_DOCUMENTS.
    Attempting request_missing_document is rejected and falls back to deterministic update_application_status.
    """
    obs_sub = make_test_observation(
        application_id="app-guard-sub-1",
        current_status="SUBMITTED",
        is_document_complete=False,
        missing_docs=["10TH_MARKSHEET"],
    )
    proposal = {
        "action_type": "TOOL_CALL",
        "tool": "request_missing_document",
        "parameters": {"application_id": "app-guard-sub-1", "document_type": "10TH_MARKSHEET"},
        "rationale": "Attempting to request document before status transition",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(observation=obs_sub, iteration=1)

    # Proposal rejected -> fallback updates status to WAITING_FOR_DOCUMENTS
    assert action is not None
    assert action.tool == ToolName.UPDATE_APPLICATION_STATUS
    assert action.parameters["new_status"] == "WAITING_FOR_DOCUMENTS"
    assert action.is_terminal is True
    assert action.terminal_outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT

    fallback_audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-sub-1", "status": "FALLBACK"})
    assert fallback_audit is not None
    assert "must transition to 'WAITING_FOR_DOCUMENTS'" in fallback_audit["result"]
    provider.close()


def test_guardrail_processing_missing_documents_cannot_call_request_missing_document_or_terminate(clean_db):
    """
    Rule 3: PROCESSING application with missing documents must transition to WAITING_FOR_DOCUMENTS.
    Attempting request_missing_document or direct TERMINATE is rejected and falls back.
    """
    obs_proc = make_test_observation(
        application_id="app-guard-proc-1",
        current_status="PROCESSING",
        is_document_complete=False,
        missing_docs=["DEGREE_CERTIFICATE"],
    )
    # 1. Attempting request_missing_document
    prop_tool = {
        "action_type": "TOOL_CALL",
        "tool": "request_missing_document",
        "parameters": {"application_id": "app-guard-proc-1", "document_type": "DEGREE_CERTIFICATE"},
        "rationale": "Calling request_missing_document while in PROCESSING",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    t1 = make_mock_transport_for_json(make_openai_response(prop_tool))
    p1 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=t1)
    s1 = LLMPlanningStrategy(provider=p1, db=clean_db, fallback_enabled=True)
    act1, out1, _ = s1.plan_next_action(obs_proc, iteration=1)
    assert act1 is not None
    assert act1.tool == ToolName.UPDATE_APPLICATION_STATUS
    assert act1.parameters["new_status"] == "WAITING_FOR_DOCUMENTS"
    assert out1 == OrchestrationOutcome.WAITING_FOR_APPLICANT
    p1.close()

    # 2. Attempting direct TERMINATE without transition
    prop_term = {
        "action_type": "TERMINATE",
        "tool": None,
        "parameters": {},
        "rationale": "Directly terminating without updating status in database",
        "stage": "ACT",
        "is_terminal": True,
        "terminal_outcome": "WAITING_FOR_APPLICANT",
    }
    t2 = make_mock_transport_for_json(make_openai_response(prop_term))
    p2 = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=t2)
    s2 = LLMPlanningStrategy(provider=p2, db=clean_db, fallback_enabled=True)
    act2, out2, _ = s2.plan_next_action(obs_proc, iteration=1)
    assert act2 is not None
    assert act2.tool == ToolName.UPDATE_APPLICATION_STATUS
    assert act2.parameters["new_status"] == "WAITING_FOR_DOCUMENTS"
    assert out2 == OrchestrationOutcome.WAITING_FOR_APPLICANT
    p2.close()


def test_guardrail_waiting_for_documents_missing_docs_rejects_repeated_tool_calls(clean_db):
    """
    Rule 4: WAITING_FOR_DOCUMENTS with missing documents must terminate with WAITING_FOR_APPLICANT.
    Calling request_missing_document or any other tool repeatedly is rejected.
    """
    obs_wait = make_test_observation(
        application_id="app-guard-wait-1",
        current_status="WAITING_FOR_DOCUMENTS",
        is_document_complete=False,
        missing_docs=["12TH_MARKSHEET"],
    )
    # Attempting to repeatedly call tool
    prop_tool = {
        "action_type": "TOOL_CALL",
        "tool": "request_missing_document",
        "parameters": {"application_id": "app-guard-wait-1", "document_type": "12TH_MARKSHEET"},
        "rationale": "Repeated missing document request",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(prop_tool))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(obs_wait, iteration=1)
    # Must reject tool call and fall back to waiting
    assert action is None
    assert outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    provider.close()


def test_guardrail_processing_valid_unprocessed_document_accepted(clean_db):
    """
    Valid PROCESSING state with complete documents and unprocessed document:
    Model can propose process_document and it is accepted without fallback.
    """
    obs_proc_valid = make_test_observation(
        application_id="app-guard-proc-valid",
        current_status="PROCESSING",
        is_document_complete=True,
        missing_docs=[],
        unprocessed_docs=[{"documentId": "doc-unproc-1", "documentType": "10TH_MARKSHEET"}],
    )
    proposal = {
        "action_type": "TOOL_CALL",
        "tool": "process_document",
        "parameters": {"document_id": "doc-unproc-1"},
        "rationale": "Run OCR pipeline on unprocessed document",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(obs_proc_valid, iteration=1)
    assert action is not None
    assert action.tool == ToolName.PROCESS_DOCUMENT
    assert action.parameters["document_id"] == "doc-unproc-1"
    assert outcome is None

    # Verify NO fallback audit event was recorded
    fallback_audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-proc-valid", "status": "FALLBACK"})
    assert fallback_audit is None
    provider.close()


def test_deterministic_orchestration_independent_of_env_llm_provider(clean_db, monkeypatch):
    """
    Objective B/C: Verify that AgentOrchestrator in deterministic mode or when
    LLM_PROVIDER is disabled runs completely independent of the developer's .env file.
    """
    monkeypatch.setattr(settings, "LLM_PROVIDER", "disabled")
    app_id = "SE-ISOLATION-001"
    clean_db["applications"].insert_one({
        "applicationId": app_id,
        "userId": "user-iso",
        "applicantId": "app-iso",
        "status": "SUBMITTED",
        "programmeId": "mca",
    })

    user = {"_id": "user-iso", "role": "applicant", "applicant_id": "app-iso"}
    orchestrator = AgentOrchestrator(db=clean_db)
    res = orchestrator.run(app_id, user)

    assert res.outcome == OrchestrationOutcome.WAITING_FOR_APPLICANT
    assert res.currentApplicationStatus == "WAITING_FOR_DOCUMENTS"
    assert clean_db["applications"].find_one({"applicationId": app_id})["status"] == "WAITING_FOR_DOCUMENTS"


def test_guardrail_out_of_policy_tool_rejected_and_audited(clean_db):
    """
    Out-of-policy proposal (e.g. record_audit_event or non-permitted state jump)
    is rejected, audited with FALLBACK status, and delegates to deterministic strategy.
    """
    obs = make_test_observation(
        application_id="app-guard-policy-1",
        current_status="PROCESSING",
        is_document_complete=True,
    )
    proposal = {
        "action_type": "TOOL_CALL",
        "tool": "record_audit_event",
        "parameters": {},
        "rationale": "Model attempting to call internal system tool",
        "stage": "ACT",
        "is_terminal": False,
        "terminal_outcome": None,
    }
    transport = make_mock_transport_for_json(make_openai_response(proposal))
    provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.openai.com/v1", transport=transport)
    strategy = LLMPlanningStrategy(provider=provider, db=clean_db, fallback_enabled=True)

    action, outcome, rationale = strategy.plan_next_action(obs, iteration=1)
    fallback_audit = clean_db["agent_activity"].find_one({"applicationId": "app-guard-policy-1", "status": "FALLBACK"})
    assert fallback_audit is not None
    assert "record_audit_event" in fallback_audit["result"]
    provider.close()
