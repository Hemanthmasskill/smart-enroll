describe("Smart Enroll - Agent Activity", () => {
  beforeEach(() => {
    cy.visitAsAdmin("/admin/agent-activity");
  });

  it("shows the observable workflow audit trail", () => {
    cy.contains("h1, h2", "Agent Activity").should("be.visible");
    cy.contains("OBSERVE → PLAN → ACT → VERIFY → RE-PLAN").should("be.visible");
    cy.contains("SE20260001").should("exist");
    cy.contains("Hemanth M.P.").should("be.visible");
    cy.contains("check_document_completeness").should("be.visible");
    cy.contains("4 of 6 required documents present").should("be.visible");
    cy.contains("private reasoning, internal chain-of-thought").should("be.visible");
  });

  it("filters the audit trail by application", () => {
    cy.get("select").eq(0).select("SE20260004");
    cy.get("tbody tr").should("have.length", 8);
    cy.get("tbody").should("contain.text", "Priya N");
    cy.get("tbody").should("contain.text", "create_exception");
    cy.get("tbody").should("not.contain.text", "Hemanth M.P.");
  });

  it("filters the audit trail by stage and status", () => {
    cy.get("select").eq(1).select("VERIFY");
    cy.get("select").eq(2).select("FLAGGED");
    cy.get("tbody tr").should("have.length", 1);
    cy.get("tbody").should("contain.text", "Name mismatch detected");
    cy.get("tbody").should("contain.text", "FLAGGED");
  });

  it("connects to live backend and displays live-connected state while ensuring demo data never appears under live badge", () => {
    // Intercept POST /api/v1/auth/login and return FastAPI AuthResponse contract (token, not accessToken)
    cy.intercept("POST", "**/api/v1/auth/login", {
      statusCode: 200,
      body: {
        role: "admin",
        name: "Admission Administrator",
        email: "admin@smartenroll.edu",
        applicantId: null,
        token: "live-jwt-token-contract-test",
      },
    }).as("adminLogin");

    cy.intercept("GET", "**/api/v1/agents/activity*", {
      statusCode: 200,
      body: [
        {
          id: "live-act-101",
          timestamp: "2026-10-27 10:00:00",
          applicationId: "SE20269999",
          applicantName: "Live Applicant 9999",
          stage: "ACT",
          tool: "check_document_completeness",
          action: "Verify live uploaded documents against criteria",
          result: "6 of 6 documents verified live",
          status: "COMPLETED",
        },
      ],
    }).as("getLiveActivity");

    cy.intercept("GET", "**/api/v1/agents/runs", {
      statusCode: 200,
      body: [
        {
          runId: "live-run-999",
          applicationId: "SE20269999",
          status: "COMPLETED",
          outcome: "WAITING_FOR_APPLICANT",
          currentApplicationStatus: "WAITING_FOR_DOCUMENTS",
          stepsCompleted: 2,
          summary: "Live run fetched with real JWT token contract",
          planner: "LLM",
          fallbackOccurred: false,
          fallbackCount: 0,
          startedAt: "2026-10-27T10:00:00Z",
          completedAt: "2026-10-27T10:00:02Z",
          steps: [],
        },
      ],
    }).as("getLiveRuns");

    cy.contains("button", "Connect Live Backend").click();
    cy.get(".live-connect-box").should("be.visible");
    cy.get('.live-connect-box input[type="email"]').type("admin@smartenroll.edu");
    cy.get('.live-connect-box input[type="password"]').type("AdminSecurePassword123!");
    cy.contains("button", "Authenticate").click();

    cy.wait("@adminLogin").its("request.body").should("deep.include", {
      email: "admin@smartenroll.edu",
      role: "admin",
    });

    // Verify successful connection using token contract
    cy.contains("Connected successfully to live FastAPI + MongoDB backend.").should("be.visible");
    cy.contains(".mode-banner", "LIVE MODE: CONNECTED TO FASTAPI & MONGODB").should("be.visible");
    cy.contains("JWT AUTHENTICATED").should("be.visible");
    cy.contains("button", "Disconnect Live Backend").should("be.visible");

    // Verify password was cleared from memory/DOM (form closed)
    cy.get('.live-connect-box input[type="password"]').should("not.exist");

    // Verify live data is displayed and demo mock data NEVER appears under the live-connected badge
    cy.get("tbody").should("contain.text", "Live Applicant 9999");
    cy.get("tbody").should("contain.text", "SE20269999");
    cy.get("tbody").should("not.contain.text", "Hemanth M.P.");
    cy.get("tbody").should("not.contain.text", "SE20260001");
    cy.get("tbody").should("not.contain.text", "Priya N");
  });

  it("handles login succeeds but live telemetry retrieval fails without presenting session as live", () => {
    cy.intercept("POST", "**/api/v1/auth/login", {
      statusCode: 200,
      body: {
        role: "admin",
        name: "Admission Administrator",
        email: "admin@smartenroll.edu",
        applicantId: null,
        token: "live-jwt-token-telemetry-fail",
      },
    }).as("loginSuccess");

    // Intercept activity as 200 so we test runs endpoint telemetry failure specifically
    cy.intercept("GET", "**/api/v1/agents/activity*", {
      statusCode: 200,
      body: [],
    }).as("emptyActivity");

    // Live telemetry retrieval fails with a backend 500 error
    cy.intercept("GET", "**/api/v1/agents/runs", {
      statusCode: 500,
      body: { detail: "Database cluster unreachable during runs retrieval" },
    }).as("failedRuns");

    cy.contains("button", "Connect Live Backend").click();
    cy.get('.live-connect-box input[type="email"]').type("admin@smartenroll.edu");
    cy.get('.live-connect-box input[type="password"]').type("ValidAdminPassword123!");
    cy.contains("button", "Authenticate").click();

    cy.wait("@loginSuccess");
    cy.wait("@failedRuns");

    // Must NOT present the session as live and must NOT display success feedback
    cy.contains("LIVE MODE: CONNECTED TO FASTAPI & MONGODB").should("not.exist");
    cy.contains("Connected successfully to live FastAPI + MongoDB backend.").should("not.exist");

    // Must accurately present authenticated state with live data error
    cy.contains(".mode-banner", "AUTHENTICATED: LIVE DATA RETRIEVAL FAILED").should("be.visible");
    cy.contains("ENDPOINT ERROR").should("be.visible");
    cy.contains("Database cluster unreachable during runs retrieval").should("be.visible");

    // Password must be cleared
    cy.get('.live-connect-box input[type="password"]').should("not.exist");

    // Policy: Demo mock data must NEVER be substituted or displayed under authenticated state
    cy.get("tbody").should("not.contain.text", "Hemanth M.P.");
    cy.get("tbody").should("not.contain.text", "Priya N");
    cy.contains("No activity matches these filters.").should("be.visible");
    cy.contains("No orchestration runs available.").should("be.visible");
  });

  it("displays live orchestration feedback using actual backend response fields (planner, stepsCompleted)", () => {
    cy.intercept("POST", "**/api/v1/auth/login", {
      statusCode: 200,
      body: {
        role: "admin",
        name: "Admission Administrator",
        email: "admin@smartenroll.edu",
        applicantId: null,
        token: "live-jwt-token-orchestrate-test",
      },
    }).as("adminLogin");

    cy.intercept("GET", "**/api/v1/agents/runs", {
      statusCode: 200,
      body: [
        {
          runId: "live-run-777",
          applicationId: "SE20267777",
          status: "COMPLETED",
          outcome: "WAITING_FOR_APPLICANT",
          currentApplicationStatus: "WAITING_FOR_DOCUMENTS",
          stepsCompleted: 2,
          summary: "Initial live run",
          planner: "LLM",
          fallbackOccurred: false,
          fallbackCount: 0,
          startedAt: "2026-10-27T10:00:00Z",
          completedAt: "2026-10-27T10:00:02Z",
          steps: [],
        },
      ],
    }).as("getLiveRuns");

    cy.intercept("GET", "**/api/v1/agents/activity*", {
      statusCode: 200,
      body: [],
    });

    // Intercept POST /api/v1/agents/orchestrate/{application_id} returning real schema
    cy.intercept("POST", "**/api/v1/agents/orchestrate/SE20267777", {
      statusCode: 200,
      body: {
        runId: "orchestrate-run-888",
        applicationId: "SE20267777",
        status: "COMPLETED",
        outcome: "WAITING_FOR_APPLICANT",
        currentApplicationStatus: "WAITING_FOR_DOCUMENTS",
        stepsCompleted: 4,
        summary: "Autonomous verification loop completed 4 steps",
        planner: "LLM",
        fallbackOccurred: false,
        fallbackCount: 0,
        startedAt: "2026-10-27T10:05:00Z",
        completedAt: "2026-10-27T10:05:04Z",
        steps: [
          {
            stepIndex: 1,
            stage: "ACT",
            tool: "check_document_completeness",
            action: "Inspect completeness",
            resultSummary: "Done",
            status: "COMPLETED",
            planner: "LLM",
          },
        ],
      },
    }).as("triggerRun");

    cy.contains("button", "Connect Live Backend").click();
    cy.get('.live-connect-box input[type="email"]').type("admin@smartenroll.edu");
    cy.get('.live-connect-box input[type="password"]').type("AdminPass123!");
    cy.contains("button", "Authenticate").click();
    cy.wait("@adminLogin");

    cy.contains("button", "Trigger Orchestrator Cycle").click();
    cy.wait("@triggerRun");

    // Verify feedback message uses verified fields planner and stepsCompleted
    cy.get(".admin-feedback").should("be.visible");
    cy.get(".admin-feedback").should("contain.text", "status: COMPLETED");
    cy.get(".admin-feedback").should("contain.text", "Outcome: WAITING_FOR_APPLICANT");
    cy.get(".admin-feedback").should("contain.text", "Planner: LLM");
    cy.get(".admin-feedback").should("contain.text", "Steps Completed: 4");
    // Ensure no undefined or non-existent fields are rendered
    cy.get(".admin-feedback").should("not.contain.text", "undefined");
    cy.get(".admin-feedback").should("not.contain.text", "plannerStrategy");
    cy.get(".admin-feedback").should("not.contain.text", "iterationsExecuted");
  });

  it("displays the correct orchestrator iteration limit matching backend default (max 15)", () => {
    cy.contains("button", "2. Project Implementation Overview").click();
    cy.get(".admin-table").should("be.visible");
    // Row for Agent Orchestration (Inc 15) must state max 15, matching backend orchestrator.py
    cy.contains("td", "Agent Orchestration (Inc 15)").parent().within(() => {
      cy.get("td").should("contain.text", "cycle limit (max 15)");
      cy.get("td").should("not.contain.text", "max 10");
    });
  });

  it("surfaces clear error when backend connection fails without faking live state", () => {
    cy.intercept("POST", "**/api/v1/auth/login", { forceNetworkError: true }).as("networkErrorLogin");

    cy.contains("button", "Connect Live Backend").click();
    cy.get(".live-connect-box").should("be.visible");
    cy.get('.live-connect-box input[type="email"]').type("admin@smartenroll.edu");
    cy.get('.live-connect-box input[type="password"]').type("TestPassword123!");
    cy.contains("button", "Authenticate").click();

    cy.wait("@networkErrorLogin");
    cy.contains("Unable to connect to live backend at http://localhost:8000/api/v1").should("be.visible");
    // Verify it stays in demo mode and does not falsely claim to be live
    cy.contains("DEMO MODE ACTIVE").should("be.visible");
    cy.contains("LIVE MODE: CONNECTED").should("not.exist");
  });
});
