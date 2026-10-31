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

    // Verify application status reflects real currentApplicationStatus from live run response
    cy.contains(".run-meta-title", "Application Status")
      .parent()
      .within(() => {
        cy.get(".run-meta-value").should("contain.text", "WAITING_FOR_DOCUMENTS");
        cy.get(".run-meta-value").should("not.contain.text", "PROCESSING");
      });
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

  it("renders the actual application status from backend run response with safe fallback", () => {
    // 0. Unit verification of getRunStatusDisplay presentation contract
    cy.window().then((win) => {
      const { getRunStatusDisplay } = win.__smartEnrollAgentActivity || {};
      expect(getRunStatusDisplay).to.be.a("function");
      expect(getRunStatusDisplay({ currentApplicationStatus: "WAITING_FOR_DOCUMENTS" })).to.deep.equal({
        title: "Application Status",
        value: "WAITING_FOR_DOCUMENTS",
        tagClass: "stage-WAITING_FOR_DOCUMENTS",
      });
      expect(getRunStatusDisplay({ currentStage: "VERIFICATION_IN_PROGRESS" })).to.deep.equal({
        title: "Legacy Workflow Stage",
        value: "VERIFICATION_IN_PROGRESS",
        tagClass: "stage-VERIFICATION_IN_PROGRESS",
      });
      expect(getRunStatusDisplay({})).to.deep.equal({
        title: "Application Status",
        value: "Application Status Unavailable",
        tagClass: "stage-UNAVAILABLE",
      });
      expect(getRunStatusDisplay(null)).to.deep.equal({
        title: "Application Status",
        value: "Application Status Unavailable",
        tagClass: "stage-UNAVAILABLE",
      });
    });

    // 1. Case 1: In default mock run (demo-run-001, SE20260001), currentApplicationStatus exists
    cy.contains(".run-meta-title", "Application Status")
      .parent()
      .within(() => {
        cy.get(".run-meta-value").should("contain.text", "WAITING_FOR_DOCUMENTS");
        cy.get(".run-meta-value").should("not.contain.text", "PROCESSING");
      });

    // Also verify when switching to demo run SE20260003 whose currentApplicationStatus is ELIGIBILITY_CHECK
    cy.contains("label", "Select Run:")
      .parent()
      .find("select")
      .select("demo-run-003");

    cy.contains(".run-meta-title", "Application Status")
      .parent()
      .within(() => {
        cy.get(".run-meta-value").should("contain.text", "ELIGIBILITY_CHECK");
      });

    // 2. Case 2 & 3: Connect live backend with legacy records simulating realistic API response contracts
    cy.intercept("POST", "**/api/v1/auth/login", {
      statusCode: 200,
      body: {
        role: "admin",
        name: "Admission Administrator",
        email: "admin@smartenroll.edu",
        applicantId: null,
        token: "live-jwt-token-legacy-fallback",
      },
    }).as("loginLegacy");

    cy.intercept("GET", "**/api/v1/agents/runs", {
      statusCode: 200,
      body: [
        {
          runId: "legacy-run-111",
          applicationId: "SE20268888",
          status: "COMPLETED",
          outcome: "COMPLETED",
          currentApplicationStatus: null,
          currentStage: "VERIFICATION_IN_PROGRESS",
          stepsCompleted: 1,
          summary: "Legacy run with currentStage only",
          startedAt: "2026-10-27T10:00:00Z",
          completedAt: "2026-10-27T10:00:02Z",
          steps: [],
        },
        {
          runId: "legacy-run-222",
          applicationId: "SE20267777",
          status: "COMPLETED",
          outcome: "COMPLETED",
          currentApplicationStatus: null,
          currentStage: null,
          stepsCompleted: 1,
          summary: "Legacy run with neither status nor stage",
          startedAt: "2026-10-27T10:00:00Z",
          completedAt: "2026-10-27T10:00:02Z",
          steps: [],
        },
      ],
    }).as("getLegacyRuns");

    cy.intercept("GET", "**/api/v1/agents/activity*", {
      statusCode: 200,
      body: [],
    });

    cy.contains("button", "Connect Live Backend").click();
    cy.get('.live-connect-box input[type="email"]').type("admin@smartenroll.edu");
    cy.get('.live-connect-box input[type="password"]').type("AdminPass123!");
    cy.contains("button", "Authenticate").click();
    cy.wait("@loginLegacy");
    cy.wait("@getLegacyRuns");

    // Case 2: When only currentStage exists, label must be "Legacy Workflow Stage", NEVER "Application Status"
    cy.contains(".run-meta-title", "Legacy Workflow Stage")
      .parent()
      .within(() => {
        cy.get(".run-meta-value").should("contain.text", "VERIFICATION_IN_PROGRESS");
      });
    cy.contains(".run-meta-title", "Application Status").should("not.exist");

    // Case 3: Select legacy-run-222 where neither exists -> must display "Application Status Unavailable"
    cy.contains("label", "Select Run:")
      .parent()
      .find("select")
      .select("legacy-run-222");

    cy.contains(".run-meta-title", "Application Status")
      .parent()
      .within(() => {
        cy.get(".run-meta-value").should("contain.text", "Application Status Unavailable");
        cy.get(".run-meta-value").should("not.contain.text", "PROCESSING");
      });
  });

  it("renders accurate planner strategy descriptions for fallback-enabled, fallback-disabled, and deterministic states", () => {
    // 1. LLM enabled with deterministic fallback enabled
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        llmProvider: "openai_compatible",
        llmEnabled: true,
        llmModel: "qwen2.5:3b",
        isLocalEndpoint: true,
        allowLocalEndpoints: true,
        fallbackEnabled: true,
        timeoutSeconds: 15.0,
        temperature: 0.0,
        availableToolsCount: 13,
        registeredTools: ["tool1", "tool2"],
      },
    }).as("statusLlmFallbackEnabled");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusLlmFallbackEnabled");
    cy.contains(".system-status-item", "Planner Strategy:").should(
      "contain.text",
      "LLM with Deterministic Fallback"
    );

    // 2. LLM enabled with fallback disabled
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        llmProvider: "openai_compatible",
        llmEnabled: true,
        llmModel: "qwen2.5:3b",
        isLocalEndpoint: true,
        allowLocalEndpoints: true,
        fallbackEnabled: false,
        timeoutSeconds: 15.0,
        temperature: 0.0,
        availableToolsCount: 13,
        registeredTools: ["tool1", "tool2"],
      },
    }).as("statusLlmFallbackDisabled");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusLlmFallbackDisabled");
    cy.contains(".system-status-item", "Planner Strategy:").should(
      "contain.text",
      "LLM (Fallback Disabled)"
    );
    cy.contains(".system-status-item", "Planner Strategy:").should(
      "not.contain.text",
      "LLM with Deterministic Fallback"
    );

    // 3. Deterministic-only mode (llmEnabled: false)
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        llmProvider: "disabled",
        llmEnabled: false,
        llmModel: "gpt-4o-mini",
        isLocalEndpoint: false,
        allowLocalEndpoints: false,
        fallbackEnabled: true,
        timeoutSeconds: 15.0,
        temperature: 0.0,
        availableToolsCount: 13,
        registeredTools: ["tool1", "tool2"],
      },
    }).as("statusDeterministic");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusDeterministic");
    cy.contains(".system-status-item", "Planner Strategy:").should(
      "contain.text",
      "Deterministic Only"
    );
  });

  it("renders accurate endpoint security descriptions distinguishing local permitted, local rejected, and remote configurations", () => {
    // 1. Local endpoint permitted (isLocalEndpoint: true, allowLocalEndpoints: true)
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        llmProvider: "openai_compatible",
        llmEnabled: true,
        llmModel: "qwen2.5:3b",
        isLocalEndpoint: true,
        allowLocalEndpoints: true,
        fallbackEnabled: true,
        timeoutSeconds: 15.0,
        temperature: 0.0,
        availableToolsCount: 13,
        registeredTools: ["tool1"],
      },
    }).as("statusLocalPermitted");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusLocalPermitted");
    cy.contains(".system-status-item", "Endpoint Security:").should(
      "contain.text",
      "Local Endpoint Permitted"
    );

    // 2. Local endpoint rejected by configuration (isLocalEndpoint: true, allowLocalEndpoints: false)
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        llmProvider: "openai_compatible",
        llmEnabled: true,
        llmModel: "qwen2.5:3b",
        isLocalEndpoint: true,
        allowLocalEndpoints: false,
        fallbackEnabled: true,
        timeoutSeconds: 15.0,
        temperature: 0.0,
        availableToolsCount: 13,
        registeredTools: ["tool1"],
      },
    }).as("statusLocalRejected");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusLocalRejected");
    cy.contains(".system-status-item", "Endpoint Security:").should(
      "contain.text",
      "Local Endpoint Rejected by Configuration"
    );

    // 3. Remote endpoint configured (isLocalEndpoint: false)
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        llmProvider: "openai",
        llmEnabled: true,
        llmModel: "gpt-4o-mini",
        isLocalEndpoint: false,
        allowLocalEndpoints: false,
        fallbackEnabled: true,
        timeoutSeconds: 15.0,
        temperature: 0.0,
        availableToolsCount: 13,
        registeredTools: ["tool1"],
      },
    }).as("statusRemote");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusRemote");
    cy.contains(".system-status-item", "Endpoint Security:").should(
      "contain.text",
      "Remote Endpoint Configured"
    );
  });

  it("displays Configuration Unavailable when status is missing or offline and does not claim Deterministic Only or Remote Endpoint Configured", () => {
    // 1. Function unit checks via window.__smartEnrollAgentActivity: missing or isLive === false returns Configuration Unavailable
    cy.window().then((win) => {
      const { getPlannerStrategyLabel, getEndpointSecurityLabel } = win.__smartEnrollAgentActivity || {};
      expect(getPlannerStrategyLabel).to.be.a("function");
      expect(getEndpointSecurityLabel).to.be.a("function");

      expect(getPlannerStrategyLabel(null)).to.equal("Configuration Unavailable");
      expect(getPlannerStrategyLabel(undefined)).to.equal("Configuration Unavailable");
      expect(getPlannerStrategyLabel({ isLive: false, llmEnabled: false })).to.equal("Configuration Unavailable");
      expect(getPlannerStrategyLabel(null)).to.not.equal("Deterministic Only");

      expect(getEndpointSecurityLabel(null)).to.equal("Configuration Unavailable");
      expect(getEndpointSecurityLabel(undefined)).to.equal("Configuration Unavailable");
      expect(getEndpointSecurityLabel({ isLive: false, isLocalEndpoint: false })).to.equal("Configuration Unavailable");
      expect(getEndpointSecurityLabel(null)).to.not.equal("Remote Endpoint Configured");
    });

    // 2. Browser E2E check: when system status endpoint is offline / returns static fallback
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 503,
      body: { detail: "Service Unavailable" },
    }).as("statusUnavailable");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusUnavailable");

    // Must display Configuration Unavailable and must NOT claim Deterministic Only or Remote Endpoint Configured
    cy.contains(".system-status-item", "Planner Strategy:").should(
      "contain.text",
      "Configuration Unavailable"
    );
    cy.contains(".system-status-item", "Planner Strategy:").should(
      "not.contain.text",
      "Deterministic Only"
    );

    cy.contains(".system-status-item", "Endpoint Security:").should(
      "contain.text",
      "Configuration Unavailable"
    );
    cy.contains(".system-status-item", "Endpoint Security:").should(
      "not.contain.text",
      "Remote Endpoint Configured"
    );

    // 3. Browser E2E check: when status payload explicitly has isLive: false
    cy.intercept("GET", "**/api/v1/agents/system-status", {
      statusCode: 200,
      body: {
        isLive: false,
        llmProvider: "disabled",
        llmEnabled: false,
        isLocalEndpoint: false,
        allowLocalEndpoints: false,
      },
    }).as("statusIsLiveFalse");

    cy.visitAsAdmin("/admin/agent-activity");
    cy.wait("@statusIsLiveFalse");

    cy.contains(".system-status-item", "Planner Strategy:").should(
      "contain.text",
      "Configuration Unavailable"
    );
    cy.contains(".system-status-item", "Endpoint Security:").should(
      "contain.text",
      "Configuration Unavailable"
    );
  });
});
