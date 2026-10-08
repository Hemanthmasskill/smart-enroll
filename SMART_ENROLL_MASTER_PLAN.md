SMART ENROLL — MASTER PROJECT CONTEXT

I want to bring you fully up to date on my Smart Enroll project.

Treat everything below as the current project context and development roadmap. The actual repository remains the final source of truth whenever repository files are available.

Do not start implementation immediately. First understand the project, current state, roadmap, architecture, and our development workflow.

1. Project Identity

Project Name: Smart Enroll

Formal Title: Autonomous Agentic AI for Intelligent College Admission Processing and Document Verification

Project Type: MCA Mini-Project

Institution: B.S. Abdur Rahman Crescent Institute of Science and Technology

Development Methodology: Agile SDLC

The project is intended to demonstrate a practical Agentic AI-assisted college admission processing and document verification system, not simply a CRUD admission portal and not simply a chatbot.

The main idea is:

Application
    ↓
Document Collection
    ↓
Document Processing
    ↓
Extraction
    ↓
Validation
    ↓
Authoritative Verification
    ↓
Exception Handling
    ↓
Eligibility Evaluation
    ↓
Application Status
    ↓
Notification
    ↓
Processing Complete

2. Our Engineering Roles

The development workflow involves three AI/engineering roles:

Me — Project Owner

I make the final project decisions, approve scope, test the application, and decide what should be implemented.

You — Gemini AI

You are the Lead Architect / technical planning and review partner.

Your responsibilities include:

Architecture

Technical direction

System design

Data-model design

API design

Agent boundaries

Implementation strategy

Task decomposition

Testing strategy

Antigravity prompt generation

Reviewing implementation results

Identifying architectural problems

Planning the next increment

Do not act merely as a prompt generator.

Google Antigravity IDE — Implementation Agent

Antigravity is responsible for:

Inspecting the actual repository

Understanding existing code

Creating an implementation plan

Implementing approved changes

Running tests

Running builds

Debugging

Reporting actual results

The overall development loop is:

Requirement
    ↓
Gemini analyzes
    ↓
Architecture / design decision
    ↓
Task breakdown
    ↓
Antigravity implementation
    ↓
Tests / verification
    ↓
Antigravity report
    ↓
Gemini reviews
    ↓
Corrections if necessary
    ↓
Next task / increment

The engineering principle is:

UNDERSTAND
    ↓
INSPECT
    ↓
PLAN
    ↓
IMPLEMENT
    ↓
VERIFY
    ↓
REPORT

3. Technology Stack

Frontend

React.js

Vite

JavaScript

React Router

Standard CSS

Cypress for E2E testing

Backend

Python

FastAPI

Pydantic V2

MongoDB

PyMongo

AI / Agentic Layer

Planned:

LLM

Agent orchestration

Specialized agents/capabilities

Tool-based workflow execution

Exception routing

Confidence/ambiguity handling

Document Processing

Planned:

OCR

PDF processing

Image processing

Document classification

Field extraction

Normalization

Cross-document comparison

Machine Learning

Python

scikit-learn

Analytics

Pandas

Matplotlib

Power BI

4. Important Architecture Principle

Smart Enroll should remain an academically credible modular monolith.

Do not unnecessarily introduce:

Microservices

Kubernetes

Message brokers

Distributed infrastructure

Complex event-driven architecture

unless there is a genuine project requirement.

The architecture should be understandable, demonstrable, maintainable, and suitable for an MCA project.

Conceptually:

React Frontend
      ↓
FastAPI REST API
      ↓
Services / Agents / Document Processing
      ↓
MongoDB

5. Deterministic Logic vs AI

This distinction is extremely important.

Deterministic logic should handle:

Eligibility thresholds

Required-document rules

Validation rules

Calculations

Application state transitions

Programme requirements

File validation

Basic consistency checks

AI/ML can handle:

Document classification

OCR-assisted extraction

Ambiguous field interpretation

Confidence assessment

Anomaly detection

Complex document comparison where appropriate

Agentic orchestration should handle:

Coordinating capabilities

Deciding what processing step should happen next

Handling uncertain results

Creating exceptions

Requesting missing information

Resuming processing after exceptions

Coordinating verification and eligibility

Do not use an LLM for deterministic rules simply to make the project appear more AI-based.

6. Document Verification Architecture

Document verification has three separate conceptual layers.

Layer 1 — Extraction

Question:

What information is present in the document?

Examples:

Name

Date of birth

Registration number

Marks

Institution

Programme

OCR belongs primarily here.

Layer 2 — Validation

Question:

Does the extracted information make sense and match the application or other documents?

Examples:

Name mismatch

DOB mismatch

Academic data mismatch

Missing required field

Invalid document structure

Layer 3 — Authoritative Verification

Question:

Can the credential be verified against an authoritative source?

Possible source:

DigiLocker

NAD

Issuer/authoritative verification system

Important:

OCR does NOT prove authenticity.

The frontend and backend should keep extraction, validation, and authoritative verification conceptually separate.

Possible statuses:

Verified

Validated

Unverified

Mismatch

Rejected

DigiLocker currently exists as a frontend simulation. Do not claim that a real government API integration exists unless it is actually implemented and verified.

7. Frontend Status

Frontend development through Increment 7 is complete and currently frozen.

The frontend includes:

Landing page

Login

Registration

Mock authentication

Applicant dashboard

Application workflow

Five-step application form

Document management

Three-layer verification UI

DigiLocker simulation

Eligibility

Application tracking

Notifications

Profile

Admin dashboard

Admin applications

Admin application details

Exceptions

Program/rules interface

Agent activity

Analytics

Cypress E2E testing

There are currently:

34 passing Cypress tests

The frontend still contains mock services/data in places.

The backend will gradually replace these mocks.

Important:

Do not break existing frontend functionality or existing Cypress tests.

8. Completed Backend Work

Increment 8 — Backend Foundation

STATUS: COMPLETE

Increment 8 established the FastAPI backend foundation and MongoDB connectivity. It was pushed to:

increment-8-backend-foundation

It includes:

FastAPI backend setup

main.py

config.py

pydantic-settings

Centralized CORS

Environment configuration

MongoDB connection

MongoDB connection pooling

FastAPI lifespan

PyMongo

/health

/api/v1/db-health

Mock /api/v1/applications/{id}

Backend tests

Increment 9 — Database Persistence & Service Layer

STATUS: COMPLETE

Purpose:

Replace hardcoded application data with MongoDB persistence and introduce a proper application service layer.

Implemented components:

backend/app/schemas/application.py

ApplicationResponse

Pydantic V2 response schema

backend/app/services/application.py

synchronous PyMongo application service

application lookup by applicantId

application creation support

backend/app/api/applications.py

Depends(get_db) integration

dynamic application lookup

temporary /seed development endpoint

backend/app/utils/seed_data.py

isolated mock application seed data

Backend test infrastructure and application API tests

Verification:

2 passed

Increment 9 tests covered application-not-found handling and seed-then-retrieve persistence.

Increment 10 — Authentication & Authorization

STATUS: COMPLETE

Purpose:

Implement real authentication, password security, JWT access tokens, protected routes, and role-based authorization while preserving the frozen frontend architecture.

Approved security architecture:

Argon2id password hashing using argon2-cffi

No Passlib dependency

Public registration does not accept a role

Public registration always creates an applicant

Admin accounts are created through a controlled backend script/manual process

One MongoDB users collection stores applicant and admin accounts

Unique index on normalized email

Duplicate email registration returns HTTP 409

JWT uses HS256

JWT claims are limited to:

sub = user MongoDB _id string

role = internal applicant or admin

exp = expiration

JWT does not contain applicant ID, application ID, email, or name

SECRET_KEY is environment-based and is not stored in source code

Bearer-token validation returns HTTP 401 for missing, invalid, or expired authentication

Role enforcement returns HTTP 403 for authenticated users without the required role

Frontend role mapping is:

frontend user ↔ backend applicant

frontend admin ↔ backend admin

Frontend auth localStorage key remains smartenroll_auth

Frontend API base remains http://localhost:8000/api/v1

Future protected API requests use Authorization: Bearer <token>

Implemented components include:

User schemas

User registration and authentication service

Argon2id password hashing and verification

JWT creation and validation

Authentication API routes

Current-user dependency

Role-based authorization dependency

Controlled admin-creation script

Authentication tests

Security hardening to exclude hashed_password from authenticated user data returned by the dependency

Security hardening implemented:

user = db["users"].find_one(
    {"_id": user_id},
    {"hashed_password": 0},
)

Verification:

23 tests passed

Additional verification included git diff --check, health endpoint checks, database-health checks, and confirmation that the frontend src/ and Cypress test suite were not modified by Increment 10.

Git commits:

49eaf77  feat: implement Increment 10 authentication and authorization
377a1df  fix: sanitize authenticated user data

Final branch at completion:

increment-10-authentication

Final working tree status:

clean

9. CURRENT STATE

The previous Increment 10 status snapshot is now superseded.

The actual current project state is:

Current branch:
increment-11-application-management

Current completed increment:
Increment 11 — Application Management

Next increment:
Increment 12 — Document Management

Current project progression:

Frontend Increment 1–7
        ↓
     COMPLETE
        ↓
Increment 8 — Backend Foundation
        ↓
     COMPLETE
        ↓
Increment 9 — Database Persistence & Service Layer
        ↓
     COMPLETE
        ↓
Increment 10 — Authentication & Authorization
        ↓
     COMPLETE
        ↓
Increment 11 — Application Management
        ↓
     COMPLETE
        ↓
Increment 12 — Document Management
        ↓
     CURRENT / NEXT

The next target architecture is:

Authenticated API Router
        ↓
Application Service
        ↓
Document Service
        ↓
MongoDB + File Storage

Increment 12 will build the backend document-management foundation on top of the completed application, persistence, and authentication layers.

10. COMPLETE DEVELOPMENT ROADMAP

The project should follow this increment roadmap unless the actual repository exposes a strong architectural reason to propose a change.

Increment 8 — Backend Foundation

STATUS: COMPLETE

Purpose:

Establish FastAPI, configuration, MongoDB connectivity, health checks, and backend testing foundation.

Increment 9 — Database Persistence & Service Layer

STATUS: COMPLETE

Purpose:

Replace hardcoded mock data with MongoDB persistence and establish the service layer.

Main components:

Pydantic Schemas
       ↓
Application Service
       ↓
MongoDB
       ↓
API Router

Increment 10 — Authentication & Authorization

STATUS: COMPLETE

Purpose:

Implement real authentication and authorization on top of the persistent backend foundation.

Scope completed:

User model

Applicant/admin roles

Registration

Password hashing

Login

Password verification

JWT access tokens

Token validation

Protected routes

Role-based authorization

401 handling

403 handling

Frontend authentication contract

Replacement of the backend authentication gap with real auth infrastructure

Expected flow:

Register
   ↓
User stored in MongoDB
   ↓
Login
   ↓
Verify password
   ↓
Generate JWT
   ↓
Frontend stores auth state
   ↓
JWT sent with API requests
   ↓
FastAPI validates token
   ↓
Role authorization

Increment 11 — Application Management

STATUS: COMPLETE

Implement the real application domain.

Scope:

Application model

Application schemas

Create application

Update application

Get application

Submit application

Application status

Applicant/application relationship

Programme selection

Basic application validation

Application states should support:

DRAFT
SUBMITTED
PROCESSING
WAITING_FOR_DOCUMENTS
VERIFICATION_IN_PROGRESS
EXCEPTION
ELIGIBILITY_CHECK
ELIGIBLE
INELIGIBLE
PROCESSING_COMPLETE

Not every application needs to pass through every state.

Increment 11 should build on Increment 9 persistence and Increment 10 authentication/authorization rather than recreating either system.

Increment 12 — Document Management

STATUS: CURRENT / NEXT

Implement backend document management.

Scope:

Document metadata

Upload handling

File validation

Allowed file types

File size validation

Document ownership

Document status

Storage strategy

Application/document relationship

Document states can include:

NOT_UPLOADED
UPLOADED
PROCESSING
VALIDATED
VERIFIED
MISMATCH
REJECTED
UNVERIFIED

The storage strategy should be practical for an MCA project and should not introduce unnecessary infrastructure.

Increment 13 — OCR & Document Processing

STATUS: UPCOMING

Implement actual document-processing capabilities.

Scope:

PDF processing

Image processing

OCR

Document classification

Field extraction

Field normalization

Extraction confidence

Handling unreadable documents

Handling unsupported formats

Possible extracted fields:

Name

DOB

Roll/registration number

Institution

Course

Marks

Percentage/CGPA

Certificate information

The architecture should support different document types without creating unnecessary duplicated logic.

Increment 14 — Document Verification

STATUS: UPCOMING

Implement the three-layer verification architecture.

Document
   ↓
Extraction
   ↓
Validation
   ↓
Authoritative Verification

Scope:

Extracted-field validation

Application/document comparison

Cross-document comparison

Name matching

DOB matching

Academic consistency

Duplicate document detection

Verification result

Confidence

Mismatch detection

DigiLocker/authoritative verification abstraction

Important:

Do not treat OCR extraction as proof of authenticity.

Increment 15 — Agentic Orchestration

STATUS: UPCOMING

This is where the Agentic AI component becomes a major backend capability.

Implement a controlled orchestration layer.

Possible capabilities/tools:

get_application
get_program_requirements
check_document_completeness
process_document
extract_document_data
verify_document
compare_applicant_details
check_eligibility
create_exception
request_missing_document
update_application_status
send_notification
record_audit_event

The agent/orchestrator should coordinate existing deterministic services and AI capabilities.

Do not allow the LLM to directly modify the database without controlled application services/tools.

Expected conceptual workflow:

Application submitted
        ↓
Orchestrator
        ↓
Check required documents
        ↓
Process documents
        ↓
Extract fields
        ↓
Validate
        ↓
Verify
        ↓
Exception if required
        ↓
Eligibility
        ↓
Update status
        ↓
Notify applicant

Do not expose hidden chain-of-thought.

Only expose safe, observable activity such as:

Requirements loaded

Documents checked

Missing document identified

Verification started

Verification completed

Eligibility evaluated

Applicant notified

Increment 16 — Eligibility Engine

STATUS: UPCOMING

Move the frontend's deterministic eligibility rules into the backend.

Scope:

Programme requirements

Academic thresholds

Required qualifications

Eligibility calculation

Eligibility result

Reasons for ineligibility

Programme-specific rules

Keep the core eligibility logic deterministic and testable.

The AI agent may invoke the eligibility service, but the LLM should not arbitrarily decide eligibility.

Increment 17 — Exception Management

STATUS: UPCOMING

Implement the exception workflow.

Possible exception types:

Name mismatch

DOB mismatch

Missing document

Unreadable document

Verification unavailable

Academic mismatch

Duplicate document

Invalid file

Eligibility conflict

Example:

Application:
Hemanth M.P.

Degree:
Hemanth Kumar

        ↓

Mismatch detected
        ↓
Exception created
        ↓
Applicant notified
        ↓
Applicant provides evidence
        ↓
Verification resumes

The system should support resuming processing after the exception is resolved.

Increment 18 — Notifications

STATUS: UPCOMING

Implement backend-generated notifications.

Scope:

Missing document notification

Verification result

Exception notification

Eligibility result

Application status changes

Read/unread state

Notification persistence

The frontend notification system should eventually consume real backend data rather than mock notifications.

Increment 19 — Analytics & Intelligence

STATUS: UPCOMING

Implement backend analytics.

Potential metrics:

Total applications

Applications by status

Verification success/failure

Exception counts

Missing-document statistics

Processing times

Eligibility statistics

Programme-wise applications

Document verification statistics

Agent activity statistics

Technology:

MongoDB
   ↓
Python
   ↓
Pandas
   ↓
Matplotlib
   ↓
Power BI

The frontend admin analytics should eventually consume backend analytics APIs where appropriate.

Increment 20 — Full System Integration

STATUS: UPCOMING

Connect the complete system:

React
   ↓
FastAPI
   ↓
MongoDB
   ↓
Application Services
   ↓
Document Processing
   ↓
Verification
   ↓
Agentic Orchestration
   ↓
Eligibility
   ↓
Exceptions
   ↓
Notifications
   ↓
Analytics

Replace remaining frontend mock data/services with real backend APIs.

Verify:

Authentication

Applicant workflow

Application persistence

Document workflow

OCR

Verification

Exceptions

Eligibility

Agent workflow

Notifications

Admin portal

Analytics

Increment 21 — Final Testing, Demo & Academic Deliverables

STATUS: UPCOMING

Final project hardening.

Testing

Unit tests

API tests

Integration tests

Frontend tests

Cypress E2E

Edge cases

Error handling

Security sanity checks

Regression testing

Demo scenarios

At minimum, demonstrate:

Normal case

Application
→ Documents
→ Verification
→ Eligibility
→ Complete

Missing document

Application
→ Missing document
→ WAITING_FOR_DOCUMENTS
→ Applicant uploads document
→ Processing resumes

Mismatch case

Application name:
Hemanth M.P.

Document name:
Hemanth Kumar

→ Mismatch
→ Exception
→ Applicant action
→ Verification resumes

Academic deliverables

Project documentation

System architecture

Database design

API documentation

Agent architecture

Flow diagrams

UML diagrams if required

Test documentation

Screenshots

PPT

Project demonstration

Viva preparation

11. Important Project Constraints

Throughout every increment:

Do not overengineer.

This is an MCA mini-project, not a production-scale enterprise platform.

Do not invent integrations.

Especially:

DigiLocker

Government APIs

OCR services

LLM APIs

If an integration is simulated, clearly label it as simulated.

Do not expose chain-of-thought.

Agent activity should show observable actions/results, not hidden reasoning.

Do not put everything inside the LLM.

Use deterministic code for deterministic rules.

Do not break existing functionality.

The frontend and existing tests must remain stable.

Do not blindly trust Antigravity reports.

Require actual:

Test results

Build results

Error output when applicable

Changed files

Verification evidence

Do not blindly follow the roadmap if the repository proves it needs adjustment.

The roadmap is the intended architecture.

The repository is the implementation source of truth.

If they conflict, identify the conflict and propose the safest correction.

12. Architectural Decision Format

For significant decisions, always explain:

DECISION:
What are we choosing?

REASON:
Why is this appropriate?

ALTERNATIVES:
What other approaches were considered?

WHY NOT:
Why were those alternatives rejected?

IMPACT:
What does this affect later?

13. How Gemini Should Handle Antigravity

When implementation is required, create precise Antigravity prompts.

Each implementation prompt should contain:

ROLE
OBJECTIVE
CURRENT CONTEXT
REPOSITORY INSPECTION
SCOPE
TECHNICAL REQUIREMENTS
CONSTRAINTS
EDGE CASES
TEST REQUIREMENTS
ACCEPTANCE CRITERIA
FINAL REPORT FORMAT

Antigravity should first inspect the repository and understand existing code before modifying anything.

For complex work, prefer:

Phase 1:
Explore + Plan

Phase 2:
Implement + Test

Do not ask Antigravity to blindly generate large amounts of code.

14. Current Project Mental Model

The project has progressed as follows:

Frontend
   ↓
Increment 1–7
   ↓
Frontend complete/frozen
   ↓
Increment 8
Backend Foundation
   ↓
COMPLETE
   ↓
Increment 9
Database Persistence & Service Layer
   ↓
COMPLETE
   ↓
Increment 10
Authentication & Authorization
   ↓
COMPLETE
   ↓
Increment 11
Application Management
   ↓
COMPLETE
   ↓
Increment 12
Document Management ← CURRENT / NEXT
   ↓
Increment 13
OCR / Document Processing
   ↓
Increment 14
Document Verification
   ↓
Increment 15
Agentic Orchestration
   ↓
Increment 16
Eligibility
   ↓
Increment 17
Exception Management
   ↓
Increment 18
Notifications
   ↓
Increment 19
Analytics
   ↓
Increment 20
Full Integration
   ↓
Increment 21
Testing / Demo / Documentation

15. MOST IMPORTANT CURRENT STATE

Right now:

Branch:
increment-11-application-management

Current completed increment:
Increment 11 — Application Management

Current target:
Increment 12 — Document Management

The immediate work for the next increment is:

Authenticated applicant/admin
        ↓
Document API
        ↓
Document Service
        ↓
MongoDB + File Storage

Increment 12 will implement the backend document-management foundation, including:

Document metadata

Upload handling

File validation

Allowed file types

File size validation

Document ownership

Document status

Storage strategy

Application/document relationship

The document-management state model should support the planned states:

DRAFT
SUBMITTED
PROCESSING
WAITING_FOR_DOCUMENTS
VERIFICATION_IN_PROGRESS
EXCEPTION
ELIGIBILITY_CHECK
ELIGIBLE
INELIGIBLE
PROCESSING_COMPLETE

Do not silently redefine Increment 11. Any proposed scope change must be explicitly presented as a change to the roadmap.

Project Memory Instruction

Please remember and retain this entire Smart Enroll project context and development roadmap as the Master Project Plan for future conversations about this project.

In future Smart Enroll discussions:

Treat this roadmap as the baseline development plan.

Remember the completed increments and their status.

Remember the current increment and Git branch.

Remember the intended architecture and technology stack.

Remember the distinction between deterministic logic, AI/ML, and Agentic AI orchestration.

Remember the roles of Project Owner, Gemini (Lead Architect), and Antigravity (Implementation Agent).

Do not redefine the increment numbering or scope unless there is a strong architectural reason.

If the plan needs to change, explicitly tell me that a change is being proposed rather than silently changing the roadmap.

Keep track of which increments are completed, current, and upcoming.

When I ask questions such as “What are we doing now?”, “What is the next increment?”, or “Where are we in the project?”, use this Master Project Plan as the baseline.

If the actual repository conflicts with the remembered plan, treat the repository as the implementation source of truth and tell me about the discrepancy.

Do not make me repeatedly explain the entire project architecture and roadmap in every new conversation if this context is already available.

The current baseline is:

Increment 8 — Backend Foundation: Complete

Increment 9 — Database Persistence & Service Layer: Complete

Increment 10 — Authentication & Authorization: Complete

Increment 11 — Application Management: Complete

Increment 12 — Document Management: Current / Next

Increment 13 onward: Follow the roadmap defined above.

Please use this document as the Smart Enroll Master Project Plan and baseline for future project discussions.

16. Master Plan Repository Rule

SMART_ENROLL_MASTER_PLAN.md is the canonical project planning document for Smart Enroll.

Before making architectural recommendations, planning a new increment, generating an Antigravity implementation prompt, or answering questions about the project's overall roadmap:

Read SMART_ENROLL_MASTER_PLAN.md first.

Treat it as the baseline project plan.

Inspect the actual source code before making implementation-specific claims.

Treat the source code and tests as the final authority for what is actually implemented.

If the master plan and repository differ, do not silently choose one. Clearly report the discrepancy.

If the development plan needs to change, explicitly propose the change and explain:

What is changing

Why it needs to change

Which increment is affected

Impact on later increments

Do not silently renumber, remove, or redefine increments.

Keep the master plan updated when a major architectural or roadmap decision is formally approved.

Use this hierarchy:

Actual Repository / Tests
        ↓
Current Implementation Reality

SMART_ENROLL_MASTER_PLAN.md
        ↓
Approved Development Roadmap

Gemini's Recommendations
        ↓
Proposed Changes / Decisions

Antigravity
        ↓
Implementation

The master plan describes where the project is intended to go.

The repository describes where the project actually is.

When these differ, identify the difference before proceeding.