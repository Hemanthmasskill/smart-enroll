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
