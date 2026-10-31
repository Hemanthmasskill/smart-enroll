# Smart Enroll — Academic Eligibility Rules Specification

## 1. Overview & Architecture

Smart Enroll enforces deterministic, server-side academic admission eligibility evaluation. 
In accordance with core system architecture, the Large Language Model (LLM) planner and agent orchestrator **never** infer, guess, or decide academic eligibility. 

All evaluations are executed by a pure deterministic engine (`app.services.eligibility.engine.evaluate_eligibility`) against canonical, versioned database rules stored in the `programme_rules` collection (Design Decision D1).

---

## 2. Programme Rules Matrix (D1)

The following four canonical programme rules are seeded idempotently with compound unique index `("programmeId", 1), ("version", 1)`:

| Programme ID | Programme Name | Min. Qualification | Min. Percentage | Mathematics Requirement | Required Documents | Entrance Exam |
|---|---|---|---|---|---|---|
| `mca` | Master of Computer Applications | Bachelor's Degree | 50.0% | Required at 10+2 or Graduation level (`10+2_OR_GRADUATION`) | All 6 canonical documents | Not Applicable |
| `mba` | Master of Business Administration | Bachelor's Degree (Any discipline) | 50.0% | Not required (`NONE`) | All 6 canonical documents | Not Applicable |
| `msc-cs` | M.Sc. Computer Science | Bachelor's Degree | 55.0% | Required at Graduation level (`GRADUATION`) | All 6 canonical documents | Not Applicable |
| `mtech-cs` | M.Tech Computer Science | Bachelor's Degree in Engineering / Technology | 60.0% | Required at Graduation level (`GRADUATION`) | All 6 canonical documents | Not Applicable |

---

## 3. Evidence Hierarchy & Evaluation Rules (D2, D3, D5, D6)

### 3.1 Verified Document Evidence (D2)
- Eligibility decisions are derived **strictly** from extracted values in documents with `validationStatus == "VALIDATED"` and `processingStatus == "COMPLETED"`.
- Form-declared values (such as applicant-entered `tenthPercentage`, `twelfthPercentage`, `ugDegree`, `cgpa`) are used solely by Layer 2 cross-checking to detect discrepancies; they are **never** used in isolation to grant admission eligibility.

### 3.2 Percentage & CGPA Conversion (D3)
- Percentage is extracted from `UG_MARKSHEET`, falling back to `DEGREE_CERTIFICATE`.
- If only a CGPA is present without a direct percentage, it is converted via:
  $$\text{Percentage} = \text{CGPA} \times \text{cgpaToPercentageFactor}$$
  The default factor is **9.5** (customizable per programme rule version and copied into evaluation evidence).
- Computations use Python `Decimal` for precision.
- Comparisons are inclusive ($\ge \text{threshold}$).
- Percentages are **never rounded up** (e.g. 49.99% fails a 50.0% threshold).
- Values outside $[0.0, 100.0]$ are rejected as invalid.

### 3.3 Mathematics Requirement (D5)
- Deterministic extraction identifies `Mathematics` or `Maths` subjects along with numeric marks on `12TH_MARKSHEET` and `UG_MARKSHEET`.
- **Found at required level:** yields `PASSED`.
- **Not found:** yields `NEEDS_REVIEW` (never `FAILED`), because OCR text omission is not conclusive proof of subject absence.

### 3.4 Outcome Hierarchy (D6)
1. **Any rule `FAILED`** $\to$ Overall outcome is **`INELIGIBLE`** (definite failure on verified evidence outranks unknowns).
2. **No failures, but any rule `NEEDS_REVIEW`** $\to$ Overall outcome is **`NEEDS_REVIEW`**.
3. **All rules `PASSED` or `NOT_APPLICABLE`** $\to$ Overall outcome is **`ELIGIBLE`**.

---

## 4. Degree Normalization Table (D4)

The degree normalization engine maps raw text strings extracted from degree certificates and marksheets to canonical qualification tuples: `(Canonical Name, Degree Family, Degree Level)`.

| Raw Pattern Match | Canonical Name | Degree Family | Degree Level |
|---|---|---|---|
| `b.e`, `b.tech`, `bachelor of engineering`, `bachelor of technology` | Bachelor of Technology | Engineering / Technology | Bachelor's Degree |
| `bca`, `bachelor of computer applications` | Bachelor of Computer Applications | Computer Applications | Bachelor's Degree |
| `b.sc`, `bsc`, `bachelor of science` | Bachelor of Science | Science | Bachelor's Degree |
| `b.com`, `bcom`, `bachelor of commerce` | Bachelor of Commerce | Commerce | Bachelor's Degree |
| `bba`, `bachelor of business administration` | Bachelor of Business Administration | Management | Bachelor's Degree |
| `b.a`, `ba`, `bachelor of arts` | Bachelor of Arts | Arts / Humanities | Bachelor's Degree |
| `b.arch`, `bachelor of architecture` | Bachelor of Architecture | Architecture | Bachelor's Degree |
| `m.e`, `m.tech`, `master of technology` | Master of Technology | Engineering / Technology | Master's Degree |
| `mca`, `master of computer applications` | Master of Computer Applications | Computer Applications | Master's Degree |
| `m.sc`, `msc`, `master of science` | Master of Science | Science | Master's Degree |
| `mba`, `master of business administration` | Master of Business Administration | Management | Master's Degree |

- **Unrecognized degree strings:** Map to `None` $\to$ yields `NEEDS_REVIEW` for manual administrative verification.
- **`mtech-cs` qualification check:** Strictly requires `Degree Family == "Engineering / Technology"`. A general Bachelor's degree (such as B.Sc or BCA) yields `FAILED` $\to$ `INELIGIBLE`.

---

## 5. Auditability & Stale Protection (D7, D8, D9)

1. **Pure Function (D7):** `evaluate_eligibility(rules, app_snapshot, docs_snapshot)` produces identical results and identical SHA-256 `inputHash` for identical inputs.
2. **Atomic Persistence (D8):** Persistence filters on `applicationId`, `status == "ELIGIBILITY_CHECK"`, and active run fencing token. Every evaluation is appended to the audit-only `eligibility_evaluations` collection.
3. **Stale Protection Gate (D9):** The orchestrator and status update tool reject transitions to `ELIGIBLE` or `INELIGIBLE` unless the persisted `inputHash` matches a freshly computed SHA-256 hash over current database records. Any subsequent document upload or tampering triggers hash mismatch and forces re-evaluation.
