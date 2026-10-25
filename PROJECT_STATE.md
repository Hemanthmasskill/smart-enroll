# Smart Enroll â€” Current Implementation State Tracking

**Maintained Project State Checkpoint**
**Last Updated:** October 19, 2026
**Repository:** [https://github.com/Hemanthmasskill/smart-enroll](https://github.com/Hemanthmasskill/smart-enroll)
**Demo Deadline:** October 26, 2026

---

## 1. Verified Main Checkpoint
- **Base Branch:** `main`
- **Base Commit Hash:** `50083805c1fe791739b3f991ffc33c79eccab65f`
- **Working-tree status:** Verify with `git status --short`; this document does not track transient working-tree status.
- **Active Implementation Branch:** `increment-15-agentic-orchestration`

---

## 2. Engineering Roles
- **Project Owner:** Hemanth (Final scope approval, requirements, user acceptance testing)
- **Architect & Technical Review Partner:** ChatGPT (Technical direction, architecture, reviews, prompt generation)
- **Implementation Agent:** Google Antigravity (Repository inspection, implementation, test execution, reporting)

---

## 3. Completed Increments and Merged Pull Requests

| Increment | Title | Merged PR / Commit | Status | Core Implemented Scope |
| :--- | :--- | :--- | :---: | :--- |
| **Increments 1â€“7** | Frontend Foundation & User Experience | Commit `ba2113f` | **COMPLETE** | React 18, Vite, React Router 6, 5-step application form, 3-layer verification UI, simulated DigiLocker, applicant & admin dashboards, Cypress test suite. |
| **Increment 8** | Backend Foundation | Commit `2238ef8` | **COMPLETE** | FastAPI monolith, Pydantic settings, CORS, MongoDB lifespan connection, `/health`, `/api/v1/db-health`. |
| **Increment 9** | Database Persistence & Service Layer | Commit `9c78e46` | **COMPLETE** | PyMongo persistence, applications collection, application schemas, seed utilities. |
| **Increment 10** | Authentication & Authorization | Commits `49eaf77`, `377a1df` | **COMPLETE** | Argon2id password hashing, HS256 JWT tokens, role-based access control (`applicant`, `admin`), email uniqueness, sanitized user data. |
| **Increment 11** | Application Management | Commits `a3604d9`, `b23cbb1` | **COMPLETE** | Application model, DRAFT $\rightarrow$ SUBMITTED transitions, 19-field completeness validation, 4 supported programmes (`mca`, `mba`, `msc-cs`, `mtech-cs`), single application per applicant constraint. |
| **Increment 12** | Document Management | **PR #1** (`992a5ad`) | **COMPLETE** | 6 logical document slots, degree certificate variants, 10MB size bounds, magic-byte MIME detection, directory traversal protection (`is_path_safe`), applicant ownership enforcement. |
| **Increment 13** | OCR & Document Processing | **PR #2** (`3a4b6a7`) | **COMPLETE** | PyMuPDF (native + scanned PDF), PIL + pytesseract for images, document classification, structured field extraction with regex and normalization, confidence calculation, graceful degradation. |
| **Increment 14** | Document Verification | **PR #3** (`5008380`) | **COMPLETE** | Layer 2 deterministic content validation (identity checks, name matching, DOB calendar parsing, percentage/CGPA tolerance, cross-document consistency) and Layer 3 synthetic authoritative verification (`SyntheticAuthoritativeVerificationProvider` with clear simulation disclosure). |

---

## 4. Verified Baseline Test Evidence

### Freshly Executed Test Runs (October 19, 2026)
- **Backend Test Suite (Pytest):**
  - **Command:** `backend\.venv\Scripts\pytest backend\tests -v`
  - **Result:** **150 passed, 1 warning in 44.25s** (100% pass rate).
  - **Test Database:** Strictly confined to isolated `smartenroll_test` database.
  - **Breakdown:**
    - `test_applications.py`: 19 passed
    - `test_auth.py`: 23 passed
    - `test_document_processing.py`: 22 passed
    - `test_document_verification.py`: 52 passed
    - `test_documents.py`: 34 passed
- **Frontend E2E Test Suite (Cypress):**
  - **Command:** `npm run cy:run` (against Vite dev server on `http://localhost:5173`)
  - **Result:** **49 passed across 12 spec files in 1m 45s** (100% pass rate, 0 failed, 0 skipped).
  - *Note on Historical Distinction:* Increment 7 originally established 34 passing tests; PR #3 added intercepted real-token document processing and deletion specs, establishing the current verified baseline of 49 passing tests.
- **Frontend Production Build:**
  - **Command:** `npm run build`
  - **Result:** Built in 814ms with **0 errors** (104 modules transformed).
- **Service Connectivity:**
  - MongoDB connection verified: `{'ok': 1.0}` on `mongodb://localhost:27017`.
  - Tesseract OCR binary verified present at `C:/Program Files/Tesseract-OCR/tesseract.exe`.
  - LLM Provider: No active OpenAI or external LLM API key present in environment or `.env`.

---

## 5. Active Increment and Task Status
- **Active Increment:** **Increment 15 â€” Agentic Orchestration** (IN PROGRESS â€” Unmerged)
- **Active Branch:** `increment-15-agentic-orchestration`
- **Completed Tasks:**
  - **Task 15.1 — Agentic Orchestration Foundation & Security Corrections** (Commit: `98ffa5a`)
    - Defined agent schemas (`AuditEventRecord`, `ToolExecutionRequest`, `ToolExecutionResult`, `ToolName`, `WorkflowStage`, `ToolStatus`) in `backend/app/schemas/agent.py`.
    - Created tool registry (`backend/app/agents/tools.py`) providing standard interfaces and execution wrappers for all 13 planned tools.
    - Wrapped existing deterministic services (Application, Document, OCR, Verification) with RBAC and applicant ownership checks.
    - Defined integration interfaces for pending services (Increments 16–18: Eligibility, Exceptions, Notifications) returning explicit `DEPENDENCY_PENDING` contracts rather than fabricated results.
    - Enforced strict server-side authorization boundaries on status transitions: applicants strictly prohibited from status changes; internal orchestrator and admin authorization enforced.
    - Implemented explicit lifecycle transition graph `ALLOWED_STATUS_TRANSITIONS` leaving database state untouched on invalid jumps.
    - Gated `ELIGIBLE`/`INELIGIBLE` on deterministic eligibility results and `PROCESSING_COMPLETE` on verified completion evidence.
    - Removed public generic tool-execution endpoint, keeping protected audit-activity queries.
    - Sanitized catch-all exception handling in `execute_tool` to prevent secret/trace leaks.
    - Added 10 dedicated regression tests in `backend/tests/test_agent_orchestration.py` (18 tests total in Task 15.1).
  - **Task 15.2 — Autonomous Orchestrator Loop, Recovery Exclusivity & Targeted Final Corrections** (Committed: `aaa975b`)
    - Created `backend/app/agents/orchestrator.py` implementing bounded lifecycle: `OBSERVE` $\rightarrow$ `PLAN` $\rightarrow$ `ACT` $\rightarrow$ `VERIFY` $\rightarrow$ `RE-PLAN`.
    - Implemented `PlanningStrategy` abstract base class and `DeterministicPlanningStrategy` for offline, deterministic orchestration over real application, document, OCR, verification, and audit services without requiring external LLM API keys.
    - **Resolution of Finding 1 — Closing Document-Claim Interleaving Gap & Fencing Order:**
      - In `_claim_or_recover_run` (`backend/app/agents/orchestrator.py`), established safe resource fencing order:
        1. Atomically stamps `supersededRunIds: {"$addToSet": stale_run_id}` across **ALL** documents belonging to the application.
        2. Revokes `activeRunId` on documents currently owned by `stale_run_id` to `recovery_fence_token`, resetting in-flight (`PROCESSING`) documents back to `UPLOADED` so they remain recoverable and processable by the replacement run.
        3. Only after resource fencing finishes, marks the stale run `ABORTED` and allows the replacement execution.
      - Refined `claim_filter` in `backend/app/services/document.py` to allow replacement runs to claim documents with superseded tokens (`f"superseded-{stale_run}"`) while strictly rejecting the superseded worker itself.
      - Reasoning guarantee: If a stale claim commits before the superseded marker, subsequent ownership revocation catches it. If the marker commits first, the claim filter rejects the stale worker with HTTP 409 Conflict.
    - **Resolution of Finding 2 — Fenced Fatal OCR Exception Handler:**
      - In `backend/app/services/document.py`, fenced the exception handler around `run_document_processing_pipeline`.
      - When `run_id` is present, the error status update requires `activeRunId: run_id` and `supersededRunIds: {"$ne": run_id}`.
      - If ownership was lost during pipeline execution, the conditional error update matches 0 documents and does NOT overwrite the document status with `FAILED`.
      - Preserves safe logging, returns HTTP 500 to the caller, and maintains existing behavior for requests without a `run_id`.
    - **Resolution of Finding 3 — Safe Failure on Execution-Exclusivity Index Initialization Failure:**
      - In `backend/app/core/database.py`, replaced `try/except Exception: pass` around index initialization with explicit error handling and `DatabaseInitializationError(RuntimeError)`.
      - When `DuplicateKeyError` occurs on unique partial index creation, runs an aggregation pipeline to find and log all conflicting applications and active/recovering run IDs without silently deleting or arbitrarily aborting executions, and raises `DatabaseInitializationError` to prevent the application from reporting successful database initialization or readiness.
      - Index migration and safe administrator recovery remain supported.
    - **Strengthened Regression Tests & True Concurrency Evidence:**
      - `test_orchestration_concurrent_recovery_attempts_cannot_both_claim`: Synchronized two concurrent threads with `threading.Barrier(2)` right before the CAS recovery call; exactly 1 succeeds and 1 gets `ALREADY_RUNNING`.
      - `test_heartbeat_races_with_stale_run_cas_prevents_takeover`: Synchronized concurrent threads with barrier and event verifying live heartbeat renewer prevents takeover by stale recovery CAS.
      - `test_crashed_recovering_run_safely_recovered_by_next_worker`: Two concurrent threads race to recover a crashed `RECOVERING` execution; exactly one wins and establishes the replacement run.
      - `test_pre_claimed_document_persistence_blocked_after_recovery_revokes_token`: Exercises real service persistence path (`process_document` and `verify_document`), verifying rejection at the persistence boundary.
      - `test_document_claim_commits_before_superseded_marker_revoked_by_subsequent_fencing`: Verifies claim committing immediately before marker is revoked by subsequent fencing and recovered by replacement run.
      - `test_fenced_fatal_ocr_exception_handler_cannot_mark_failed_if_ownership_lost`: Verifies real service exception handler cannot mark document `FAILED` when ownership is revoked.
      - `test_database_initialization_fails_safely_on_duplicate_active_runs`: Verifies safe failure, conflict reporting, and successful recovery on duplicate active runs.
    - **Decoupled Heartbeat & Progress-Version Consistency:**
      - `HeartbeatRenewer` increments `leaseVersion` monotonically without touching `progressVersion`. `progressVersion` advances strictly on workflow step progression, preventing self-fencing during long-running tool execution.
    - **Sanitized Failures & Lifecycle Status Mapping:**
      - Lifecycle status (`OrchestrationRunStatus`) and workflow outcomes (`OrchestrationOutcome`) remain strictly separated. Terminal workflow outcomes release the partial unique index by transitioning to `COMPLETED`.
      - Top-level exception handling in `AgentOrchestrator.run()` logs complete stack traces internally while returning and persisting a generic safe failure summary, preventing credential or filesystem leakage.
    - Implemented authenticated orchestration endpoints in `backend/app/api/agents.py`:
      - `POST /api/v1/agents/orchestrate/{application_id}` (applicant ownership or admin authorized)
      - `GET /api/v1/agents/orchestrate/{application_id}/status` (retrieves latest run status)
      - `GET /api/v1/agents/orchestrate/runs/{run_id}` (retrieves specific run with step audit trail)
    - Total orchestration regression suite expanded to **56 dedicated tests** in `backend/tests/test_agent_orchestration.py`.
  - **Task 15.3 — LLM Provider Integration & Agentic Hardening** (Implemented & Refined — PR #4 Open & In Progress)
    - Implemented `LLMProvider` abstract base class and `OpenAICompatibleProvider` in `backend/app/agents/providers.py` using the existing `httpx` dependency without introducing external SDKs, LangChain, or agent frameworks.
    - Universal OpenAI-compatible API support for OpenAI, Groq, Ollama, vLLM, or LM Studio endpoints with bounded timeout, temperature, and masked credential representation.
    - Built-in strict SSRF destination validation (`validate_endpoint_url`): permits unambiguous local loopback endpoints (such as a local Ollama instance) ONLY when explicitly enabled by configuration (`LLM_ALLOW_LOCAL_ENDPOINTS=True`), while continuing to strictly reject link-local (169.254.x.x), RFC 1918 private, unspecified (0.0.0.0, ::), and restricted domain suffixes (.local, .internal, .arpa) even when local endpoints are enabled.
    - Configured local loopback detection (`is_local_endpoint`) and updated `AgentOrchestrator.__init__` to allow local Ollama endpoint initialization without an API key while strictly enforcing valid API credentials for remote endpoints, with automatic safe fallback to deterministic strategy if provider validation fails.
    - Enhanced provider client to omit the `Authorization` header entirely when `api_key` is not configured, ensuring clean compatibility with local Ollama endpoints.
    - Implemented `LLMPlanningStrategy` in `backend/app/agents/llm_planner.py` conforming to the existing `PlanningStrategy` ABC.
    - Sanitized observation serializer (`sanitize_observation_for_llm`) enforcing strict privacy by excluding all applicant PII (names, emails, phone numbers, raw OCR text, document contents) and providing only minimal workflow status tokens.
    - Strict output proposal validation against `LLMPlanProposal` schema with `ConfigDict(extra="forbid")`, enforcing permitted tool names, expected parameters, and terminal outcomes.
    - **Strengthened Server-Side Workflow Guardrails (`_validate_and_build_action` & `_validate_terminal_outcome`):**
      - **Rule 1 (DRAFT):** An unsubmitted draft cannot execute any tool (`request_missing_document`, `update_application_status`, notifications). The only valid action is `TERMINATE` with outcome `WAITING_FOR_APPLICANT`. Any tool proposal or conflicting terminal outcome is rejected and falls back safely to deterministic logic.
      - **Rule 2 (SUBMITTED with missing documents):** Application must transition to `WAITING_FOR_DOCUMENTS` via `update_application_status` with terminal outcome `WAITING_FOR_APPLICANT`. Proposals attempting to call `request_missing_document` or terminate directly without updating status are rejected.
      - **Rule 3 (PROCESSING with missing documents):** Preserves deterministic transition: application must transition to `WAITING_FOR_DOCUMENTS` via `update_application_status` and terminate with `WAITING_FOR_APPLICANT`. Direct tool calls or terminations are rejected.
      - **Rule 4 (WAITING_FOR_DOCUMENTS with missing documents):** Application must terminate with `WAITING_FOR_APPLICANT`. Repeated tool calls (`request_missing_document` or others) for the same incomplete workflow are rejected. When documents become complete, processing resumes deterministically.
    - Reorganized `SYSTEM_PLANNING_PROMPT` so critical state-priority invariants appear before the tool catalogue, guiding model output while relying strictly on server-side guardrails as the security boundary.
    - Seamless deterministic fallback: on provider failure, timeout, HTTP 429 rate limit, HTTP 500 error, network disconnection, malformed JSON, or guardrail rejection, gracefully falls back to `DeterministicPlanningStrategy` and records a sanitized `FALLBACK` audit record in `agent_activity`.
    - **Deterministic Test Isolation:** Added autouse test fixture `isolate_deterministic_orchestration` in `backend/tests/test_agent_orchestration.py` to ensure orchestration, concurrency, fencing, recovery, and persistence tests remain completely independent of the developer's local `.env` configuration (`LLM_PROVIDER="openai_compatible"`), without altering production code defaults or modifying the user's `.env`.
    - **Live Local Ollama Smoke-Test Verification (Qwen2.5 3B via `http://127.0.0.1:11434/v1`):**
      - *Scenario 1 (DRAFT Application):* Model proposed `TERMINATE` with outcome `WAITING_FOR_APPLICANT`. Validation: **PASSED**. Effective action: `None`, effective outcome: `WAITING_FOR_APPLICANT`. Fallback invoked: **False**.
      - *Scenario 2 (SUBMITTED with Missing Docs):* Model proposed `request_missing_document` tool call. Validation: **REJECTED** by domain guardrail. Deterministic fallback invoked: **True**. Effective action: `update_application_status` (`new_status="WAITING_FOR_DOCUMENTS"`), effective outcome: `WAITING_FOR_APPLICANT`.
      - *Scenario 3 (PROCESSING with Unprocessed Document):* Model proposed `process_document` tool call with valid document ID. Validation: **PASSED**. Effective action: `process_document`, effective outcome: `None`. Fallback invoked: **False**.
      - *Model Quality vs System Safety Distinction:* Small local models exhibit tool bias towards registered tools like `request_missing_document` when missing document fields are present in observations; server-side domain guardrails detect and reject invalid proposals, delegating safely to deterministic fallback and preserving workflow invariants.
    - Added 8 dedicated regression tests in `backend/tests/test_agent_llm_planner.py` covering Rules 1–4, valid PROCESSING proposals, test isolation, and out-of-policy tool rejection (expanding the suite to 52 tests).
    - Total backend test suite expanded to **258 passing tests** (100% pass rate).
  - **Supported Guarantees & Documented Limitations:**
    - *Guarantees:* Single active execution per application enforced across both `RUNNING` and `RECOVERING` states by database partial unique index; atomic CAS ensures exactly one worker acquires recovery ownership; crashed recoverers are safely detected and taken over without abandonment; safe recovery resource revocation order closes the document claim interleaving gap; fatal OCR exception handler is strictly fenced so stale workers cannot mark documents `FAILED`; active workers maintain lease via background heartbeats without self-fencing; model-backed planning strictly operates as an untrusted proposal generator with automatic deterministic fallback; terminal outcomes cannot bypass deterministic eligibility evaluation; model-proposed `FAILED` is rejected without explicit backend failure evidence; circular manual-review justifications are prevented by requiring independent workflow evidence before accepting `MANUAL_REVIEW_REQUIRED` or allowing transitions to `EXCEPTION`; `WAITING_FOR_APPLICANT` requires missing required documents in `WAITING_FOR_DOCUMENTS`; SSRF endpoint validation fails closed on DNS resolution failure while preserving loopback destinations without arbitrary remote bypass; zero PII transmitted to external models; database initialization fails loudly and safely if execution-exclusivity indexes cannot be built; local loopback endpoints (such as Ollama) can run keyless when local endpoints are explicitly permitted, while remote providers strictly require valid authentication credentials; arbitrary domain suffixes (`.local`, `.internal`, `.arpa`) do not receive keyless privileges; server-side domain guardrails enforce critical workflow state invariants across DRAFT, SUBMITTED, PROCESSING, and WAITING_FOR_DOCUMENTS regardless of LLM proposal.
    - *Limitations of Standalone MongoDB:* Without a replica set or mongos cluster, multi-document ACID transactions (`start_session` / `session.start_transaction`) are not available. Cross-collection consistency between `orchestration_runs`, `applications`, and `documents` is guaranteed via strictly linearized conditional atomic single-document updates and monotonic fencing tokens (`supersededRunIds`), not distributed 2PC.
    - *Model Limitations:* 3B-parameter models may exhibit tool-selection bias when fields such as `missingDocumentTypes` are present; prompt engineering improves guidance but cannot replace server-side code validation.
  - **Freshly Verified Test Evidence (Task 15.3 Guardrails & Test Isolation):**
    - Pytest LLM Planner Suite: `backend\.venv\Scripts\pytest backend\tests\test_agent_llm_planner.py -v` $\rightarrow$ **52 passed in 1.44s** (100% pass rate).
    - Pytest Deterministic Orchestration Suite: `backend\.venv\Scripts\pytest backend\tests\test_agent_orchestration.py -v` $\rightarrow$ **56 passed, 1 warning in 13.06s** (100% pass rate with `.env` configured for live Ollama).
    - Pytest Full Backend Suite: `backend\.venv\Scripts\pytest backend\tests -v` $\rightarrow$ **258 passed, 1 warning in 30.72s** (100% pass rate).
    - Live Ollama Smoke Test (`qwen2.5:3b` via Ollama): 3 synthetic scenarios evaluated; 2 model proposals accepted directly, 1 invalid proposal rejected by server-side guardrail with deterministic fallback producing the required transition. Effective workflow outcome was correct in all 3 tested scenarios (distinguishing model proposal quality from system safety).
    - Git Check: `git diff --check` $\rightarrow$ Passed with **0 whitespace or formatting errors**.
- **Next Task:** Complete review of local Task 15.3 refinements, stage/commit and push verified changes to branch `increment-15-agentic-orchestration`, and then complete PR #4 review and merge into `main` after project-owner approval.

---

## 6. Outstanding Work Roadmap (Preserving Full Approved Scope)
- [ ] **Increment 15 â€” Agentic Orchestration** (Foundation, Orchestrator loop, Tool coordination)
- [ ] **Increment 16 â€” Eligibility Engine** (Deterministic criteria evaluation, programme rules API)
- [ ] **Increment 17 â€” Exception Management** (9 exception types, severity mapping, auto-resumption)
- [ ] **Increment 18 â€” Notifications** (Milestone notifications, read/unread state tracking)
- [ ] **Increment 19 â€” Analytics & Intelligence** (PyMongo aggregation pipelines, dashboard statistics)
- [ ] **Increment 20 â€” Full System Integration** (Wire React frontend to real backend, eliminate mocks)
- [ ] **Increment 21 â€” Final Testing, Demo & Academic Deliverables** (E2E hardening, 3 demo scenarios, MCA documentation)

---

## 7. State Update Rule
`PROJECT_STATE.md` is the canonical, maintained record of the implementation state. After each increment or task is completed, verified, and merged, this file must be updated with the new commit hash, test results, and next task. The master plan (`SMART_ENROLL_MASTER_PLAN.md`) remains the frozen definition of the overall architecture, requirements, and scope.
