# Security Policy: Smart Enroll

## 1. Supported Versions

Security updates, vulnerability patches, and integrity fixes are applied to the following active branches:

| Version / Branch | Supported | Release State |
| :--- | :--- | :--- |
| `main` (Increment 15 baseline) | :white_check_mark: Yes | Current Hardened Baseline |
| `hardening/*` | :white_check_mark: Yes | Active Remediation & Audit Fixes |
| Legacy / Feature branches | :x: No | Subsumed by `main` |

---

## 2. Reporting a Vulnerability

We take the security and integrity of candidate data, educational records, and automated admission workflows seriously.

If you discover a security vulnerability in Smart Enroll:
1. **Do not create public GitHub issues or public pull requests** detailing the vulnerability.
2. Report the vulnerability privately to the security and engineering team via email:
   - **Email:** `security@smartenroll.edu` (or designated repository administrators).
3. **Include in your report:**
   - Detailed description of the vulnerability and attack vector.
   - Steps to reproduce or proof-of-concept (PoC) exploit scripts/payloads.
   - Potential impact on candidate confidentiality, integrity, or system availability.
   - Any remediation suggestions.

### Response SLA & Coordination
- **Acknowledgment:** Within 24 business hours.
- **Triage & Severity Assessment:** Within 72 business hours.
- **Remediation & Patch Deployment:** Critical issues (CVSS >= 9.0) patched within 7 calendar days; high/medium issues within 14–30 calendar days.
- **Coordinated Disclosure:** Public disclosure occurs only after patches have been committed and verified.

---

## 3. Core Security Architecture & Trust Boundaries

### 3.1 Strict Separation of Deterministic Rules and LLM Planner
- Smart Enroll enforces an **architectural trust boundary** between generative LLM reasoning and the deterministic decision engine.
- **Deterministic Supremacy:** The pure mathematical state-transition table (`compute_expected_action`) is the authoritative source of truth for all workflow status transitions and tool selections.
- **Strict Parameter Schemas:** All LLM tool call proposals are validated against strict per-tool schemas (`TOOL_PARAM_SCHEMAS`). Parameter tampering, path traversal (`../`, absolute paths), and cross-application document IDs are rejected immediately.
- **Fallback Guardrails:** If the LLM proposes an out-of-policy tool, invalid status transition, unapproved terminal state, or malformed parameters, the orchestrator rejects the proposal, logs an audit event (`action="llm_proposal_rejected"`, `status="FALLBACK"`), and executes the deterministic action.
- **Unbuilt Increments Barrier:** Increments 16–21 (Autonomous Eligibility Engine, Notifications, Exceptions, Analytics, DigiLocker live integrations) are strictly gated with `DEPENDENCY_PENDING`. No agent or LLM prompt can invent or advance eligibility without the authoritative backend service.

### 3.2 Endpoint Security & Rejection of Local Endpoints by Default
- **Remote HTTPS Enforced:** LLM remote endpoints must start with `https://`. Unencrypted `http://` remote endpoints are rejected.
- **Local Loopback Gating:** Connecting the LLM orchestrator to local loopback endpoints (such as `http://localhost:11434` or `http://127.0.0.1:11434` for Ollama/vLLM) is **disabled by default** (`LLM_ALLOW_LOCAL_ENDPOINTS=false`).
- In multi-tenant and production deployments, local loopback calls are blocked to prevent Server-Side Request Forgery (SSRF) against host services.

### 3.3 Authentication & Authorization
- **Argon2id Password Hashing:** User passwords are encrypted with Argon2id using secure salt and work factors. Weak passwords failing the 10+ character policy (uppercase, lowercase, digit, special character, common dictionary check) are rejected at registration and administration utilities.
- **Constant-Time Verification:** Login attempts for non-existent accounts execute a dummy Argon2id verification (`DUMMY_HASH`) to prevent user enumeration via timing attacks.
- **JWT Cryptographic Integrity:** Access tokens are signed with HMAC-SHA256 (minimum 32-character secret key). Claims strictly enforce issuer (`iss="smart-enroll"`), audience (`aud="smart-enroll-api"`), expiration (`exp`), and active user session version (`tokenVersion`).
- **Immediate Session Revocation:** Changing passwords or administrative revocation increments `tokenVersion`, invalidating all issued JWT tokens immediately.
- **Role-Based Access Control (RBAC):** Gated by explicit `RequireRole(["admin"])` and `RequireRole(["applicant"])` dependencies. Unauthenticated calls return HTTP 401; unauthorized roles receive HTTP 403.
- **Strict Horizontal Ownership:** Every applicant resource (application, documents, OCR extractions, verification results, audit events) is filtered by `userId == str(current_user["_id"])`. Cross-applicant access attempts return HTTP 403 Forbidden.

### 3.3.1 JWT Claim Validation & Token Migration Strategy
- **Mandatory Claims:** Every access token submitted to `/api/v1` must include all of the following claims:
  - `iss`: strictly `"smart-enroll"`
  - `aud`: strictly `"smart-enroll-api"`
  - `sub`: valid MongoDB ObjectId string referencing the user
  - `role`: user role (`"applicant"` or `"admin"`)
  - `exp`: token expiration timestamp
  - `tokenVersion`: positive integer matching the user's active session version in MongoDB
- **Rejection Policy:** Any token missing any of the above claims, or carrying a mismatched `iss`, `aud`, or `tokenVersion`, is immediately rejected with HTTP 401 Unauthorized.
- **Migration Strategy for Existing Sessions:**
  1. **Automated Client Handling:** The frontend `apiClient` intercepts HTTP 401 responses, purges cached session data from local storage, and prompts the user to re-authenticate at `/login`.
  2. **Seamless Issuance:** Upon successful authentication (`/api/v1/auth/login` or `/api/v1/auth/register`), the backend generates a modern, fully compliant token equipped with `iss`, `aud`, and the current user's `tokenVersion`.
  3. **Database Consistency:** Legacy user documents lacking the `tokenVersion` field are automatically treated as `tokenVersion: 1`. Administrators may backfill legacy collections during maintenance using:
     ```javascript
     db.users.updateMany({ tokenVersion: { $exists: false } }, { $set: { tokenVersion: 1 } });
     ```
  4. **Zero-Downtime Revocation:** Password changes or security incidents increment `tokenVersion` on the target user record, immediately invalidating all legacy and active tokens globally.

### 3.4 Storage & Encryption at Rest
- **Storage Directory:** Document files are stored in `STORAGE_DIR` under cryptographically randomized UUID filenames, decoupling logical names from disk paths.
- **Encryption at Rest:** In production environments, `STORAGE_DIR` **must reside on an encrypted volume** using LUKS / dm-crypt (Linux), BitLocker (Windows), or AWS EBS volume encryption with customer-managed KMS keys.
- **Data Retention & Draft Hygiene:** Abandoned draft applications and unlinked files older than `RETENTION_DAYS` (default 30 days) are purged via `cleanup_abandoned_drafts.py`.
- **Upload Antivirus Scanning:** File uploads are inspected through the `UploadScanner` interface before storage commitment. ClamAV integration is supported via `UPLOAD_SCANNER=clamav`.

### 3.5 Rate Limiting & Operational Security
- In-memory sliding window rate limiting throttles authentication endpoints (login: 5/min per IP+email; registration: 3/min per IP) and resource-heavy processing operations (document upload/process/verify: 10/min; orchestration: 5/min).
- Sensitive credentials (passwords, tokens, API keys) are masked across all server logging via `SensitiveDataRedactionFilter`.
- `X-Request-ID` correlation headers trace all requests from client through services.

### 3.6 Application Identifier Specification
- **Canonical Format:** Application IDs follow the strict 11-character sequential pattern `SE<YYYY><5-digit sequence>`, for example `SE202600001`.
- **Atomic Concurrency Guarantee:** IDs are generated atomically using MongoDB `find_one_and_update` on the `counters` collection with `$inc: {seq: 1}`, ensuring gapless and collision-free identifiers under high concurrency.
- **Exhaustion & Safety:** Supports up to 99,999 sequential applications per academic year; sequence exhaustion raises a hard runtime exception rather than wrapping or colliding.
