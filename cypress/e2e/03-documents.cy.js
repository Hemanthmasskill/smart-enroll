import { getVerificationStatus } from "../../src/services/api";

describe("Smart Enroll - Documents and Verification", () => {
  it("shows the expected document state", () => {
    cy.visitAsApplicant("/documents");

    cy.contains("Documents").should("be.visible");
    cy.contains("4 of 6 required documents submitted.").should("be.visible");
    cy.contains("10th Marksheet").should("be.visible");
    cy.contains("Degree / Provisional Certificate").should("be.visible");
    cy.contains("Transfer Certificate").should("be.visible");
    cy.contains("Government ID").should("be.visible");
  });

  it("opens the three-layer verification panel", () => {
    cy.visitAsApplicant("/documents");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "View").click();
    });

    cy.get('[role="dialog"][aria-label="Document Verification"]').within(() => {
      cy.contains("OCR Extraction").should("be.visible");
      cy.contains("Content Validation").should("be.visible");
      cy.contains("Authoritative Verification").should("be.visible");
      cy.contains("OCR extraction confirms only what the document states").should("be.visible");
      cy.get('button[aria-label="Close dialog"]').click();
    });
  });

  it("uploads and removes a previously missing document", () => {
    cy.visitAsApplicant("/documents");

    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.get('input[type="file"]').selectFile(
        {
          contents: Cypress.Buffer.from("Smart Enroll Cypress mock PDF"),
          fileName: "transfer_certificate.pdf",
          mimeType: "application/pdf",
        },
        { force: true }
      );
      cy.contains("transfer_certificate.pdf", { timeout: 4000 }).should("be.visible");
      cy.contains("button", "Remove").click();
    });

    cy.get('[role="dialog"][aria-label="Remove document"]').within(() => {
      cy.contains("button", "Remove").click();
    });

    cy.contains(".document-card", "Transfer Certificate", { timeout: 3000 }).within(() => {
      cy.contains("Drag and drop, or click to upload").should("be.visible");
    });
  });

  it("exercises intercepted real-token frontend deletion branch (mocked HTTP layer, not live backend)", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: "doc_10th_real",
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
      {
        id: "doc-12th",
        documentId: null,
        documentType: "12TH_MARKSHEET",
        name: "12th Marksheet",
        required: true,
        status: "NOT_UPLOADED",
        originalFileName: null,
        fileName: null,
        uploadedAt: null,
      },
      {
        id: "doc-ug-marksheet",
        documentId: null,
        documentType: "UG_MARKSHEET",
        name: "Undergraduate Marksheet",
        required: true,
        status: "NOT_UPLOADED",
        originalFileName: null,
        fileName: null,
        uploadedAt: null,
      },
      {
        id: "doc-degree",
        documentId: null,
        documentType: "DEGREE_CERTIFICATE",
        documentVariant: null,
        name: "Degree / Provisional Certificate",
        required: true,
        status: "NOT_UPLOADED",
        originalFileName: null,
        fileName: null,
        uploadedAt: null,
      },
      {
        id: "doc-transfer",
        documentId: "doc_transfer_backend_123",
        documentType: "TRANSFER_CERTIFICATE",
        name: "Transfer Certificate",
        required: true,
        status: "UPLOADED",
        originalFileName: "transfer_certificate.pdf",
        fileName: "transfer_certificate.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
      {
        id: "doc-govt-id",
        documentId: null,
        documentType: "GOVERNMENT_ID",
        name: "Government ID",
        required: true,
        status: "NOT_UPLOADED",
        originalFileName: null,
        fileName: null,
        uploadedAt: null,
      },
    ];

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocs");

    cy.intercept("DELETE", "**/api/v1/documents/doc_transfer_backend_123", {
      statusCode: 200,
      body: { detail: "Document deleted successfully.", documentId: "doc_transfer_backend_123" },
    }).as("deleteBackendDoc");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocs");

    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.contains("transfer_certificate.pdf").should("be.visible");
      cy.contains("button", "Remove").click();
    });

    cy.get('[role="dialog"][aria-label="Remove document"]').within(() => {
      cy.contains("button", "Remove").click();
    });

    cy.wait("@deleteBackendDoc").then((interception) => {
      expect(interception.request.url).to.match(/\/api\/v1\/documents\/doc_transfer_backend_123$/);
      expect(interception.request.headers.authorization).to.equal(`Bearer ${realSession.token}`);
    });

    cy.contains(".document-card", "Transfer Certificate", { timeout: 3000 }).within(() => {
      cy.contains("Drag and drop, or click to upload").should("be.visible");
    });
    cy.contains("Transfer Certificate removed.").should("be.visible");
  });

  it("surfaces real-token frontend deletion error when backend deletion fails (mocked HTTP layer, not live backend)", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-transfer",
        documentId: "doc_transfer_fail_456",
        documentType: "TRANSFER_CERTIFICATE",
        name: "Transfer Certificate",
        required: true,
        status: "UPLOADED",
        originalFileName: "transfer_certificate.pdf",
        fileName: "transfer_certificate.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsFail");

    cy.intercept("DELETE", "**/api/v1/documents/doc_transfer_fail_456", {
      statusCode: 500,
      body: { detail: "Storage disk failure during deletion." },
    }).as("failDeleteBackendDoc");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsFail");

    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.contains("button", "Remove").click();
    });

    cy.get('[role="dialog"][aria-label="Remove document"]').within(() => {
      cy.contains("button", "Remove").click();
    });

    cy.wait("@failDeleteBackendDoc").then((interception) => {
      expect(interception.request.url).to.match(/\/api\/v1\/documents\/doc_transfer_fail_456$/);
      expect(interception.request.headers.authorization).to.equal(`Bearer ${realSession.token}`);
    });

    cy.contains("Remove failed: Storage disk failure during deletion.").should("be.visible");
    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.contains("transfer_certificate.pdf").should("be.visible");
    });
  });

  it("surfaces error and does not invoke mock deletion when backend documentId is missing in real-token session", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-transfer",
        documentId: null, // Missing backend document ID
        documentType: "TRANSFER_CERTIFICATE",
        name: "Transfer Certificate",
        required: true,
        status: "UPLOADED",
        originalFileName: "transfer_certificate.pdf",
        fileName: "transfer_certificate.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsMissingId");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsMissingId");

    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.contains("button", "Remove").click();
    });

    cy.get('[role="dialog"][aria-label="Remove document"]').within(() => {
      cy.contains("button", "Remove").click();
    });

    cy.contains("Remove failed: Cannot delete document: missing backend document identifier.").should("be.visible");
    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.contains("transfer_certificate.pdf").should("be.visible");
    });
  });

  it("triggers document processing in mock session and shows OCR status", () => {
    cy.visitAsApplicant("/documents");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
      cy.contains(".document-card-ocr-badge", "OCR: 90%", { timeout: 4000 }).should("be.visible");
      cy.contains("button", "Reprocess").should("be.visible");
      cy.contains("button", "View").click();
    });

    cy.get('[role="dialog"][aria-label="Document Verification"]').within(() => {
      cy.contains("OCR Extraction").should("be.visible");
      cy.contains("Candidate Name").should("be.visible");
      cy.contains("Hemanth M.P.").should("be.visible");
      cy.contains("Roll / Registration No").should("be.visible");
      cy.contains("2022MCA041").should("be.visible");
      cy.contains("OCR extraction confirms only what the document states").should("be.visible");
      cy.get('button[aria-label="Close dialog"]').click();
    });

    cy.contains("OCR processing complete for \"10th Marksheet\"").should("be.visible");
  });

  it("exercises intercepted real-token document processing API and renders extracted fields (mocked HTTP layer)", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: "doc_10th_real",
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    const mockProcessingResult = {
      documentId: "doc_10th_real",
      applicationId: "SE20260001",
      documentType: "10TH_MARKSHEET",
      processingState: "COMPLETED",
      engine: "pymupdf+tesseract-ocr",
      pageCount: 1,
      textExtracted: true,
      overallConfidence: 0.92,
      classification: {
        predictedType: "10TH_MARKSHEET",
        confidence: 0.95,
        typeMismatch: false,
      },
      fields: {
        candidateName: { rawValue: "Priya Sharma", normalizedValue: "Priya Sharma", confidence: 0.95 },
        dob: { rawValue: "15/08/2004", normalizedValue: "2004-08-15", confidence: 0.92 },
        registrationNumber: { rawValue: "1234567", normalizedValue: "1234567", confidence: 0.90 },
        percentage: { rawValue: "90.0%", normalizedValue: 90.0, confidence: 0.92 },
      },
    };

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsForProcessing");

    cy.intercept("POST", "**/api/v1/documents/doc_10th_real/process", {
      statusCode: 200,
      body: mockProcessingResult,
    }).as("processDoc");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsForProcessing");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
    });

    cy.wait("@processDoc").then((interception) => {
      expect(interception.request.url).to.match(/\/api\/v1\/documents\/doc_10th_real\/process$/);
      expect(interception.request.headers.authorization).to.equal(`Bearer ${realSession.token}`);
    });

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains(".document-card-ocr-badge", "OCR: 92%").should("be.visible");
      cy.contains("button", "Reprocess").should("be.visible");
      cy.contains("button", "View").click();
    });

    cy.get('[role="dialog"][aria-label="Document Verification"]').within(() => {
      cy.contains("OCR Extraction").should("be.visible");
      cy.contains("Candidate Name").should("be.visible");
      cy.contains("Priya Sharma").should("be.visible");
      cy.contains("Date of Birth").should("be.visible");
      cy.contains("2004-08-15").should("be.visible");
      cy.contains("Percentage").should("be.visible");
      cy.contains("90%").should("be.visible");

      // Verify Finding B: OCR completion does not invent positive validation claim
      cy.contains("Content Validation").should("be.visible");
      cy.contains("Pending — validation not performed").should("be.visible");
      cy.contains("Format matches requirements").should("not.exist");
      cy.contains("Verified via DigiLocker/NAD").should("not.exist");
      cy.contains("Authoritative verification pending").should("be.visible");
      cy.contains("OCR extraction confirms only what the document states, not that it is genuine.").should("be.visible");

      cy.get('button[aria-label="Close dialog"]').click();
    });

    cy.contains("OCR processing complete for \"10th Marksheet\" (92% confidence)").should("be.visible");
  });

  it("handles HTTP 200 with processingState FAILED, displays failure state, and preserves retry behavior", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: "doc_10th_failed_state",
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    const failedProcessingResult = {
      documentId: "doc_10th_failed_state",
      applicationId: "SE20260001",
      documentType: "10TH_MARKSHEET",
      processingState: "FAILED",
      engine: "pymupdf+tesseract-ocr",
      pageCount: 1,
      textExtracted: false,
      overallConfidence: 0.0,
      errorMessage: "Tesseract OCR engine is not installed or discoverable on server.",
      warnings: [],
      classification: {
        predictedType: null,
        confidence: 0.0,
        typeMismatch: false,
      },
      fields: {},
    };

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsForFailedState");

    cy.intercept("POST", "**/api/v1/documents/doc_10th_failed_state/process", {
      statusCode: 200,
      body: failedProcessingResult,
    }).as("processDocFailedState");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsForFailedState");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
    });

    cy.wait("@processDocFailedState");

    // Must NOT claim successful completion
    cy.contains("OCR processing complete").should("not.exist");

    // Surfaces returned errorMessage
    cy.contains(
      'Processing failed for "10th Marksheet": Tesseract OCR engine is not installed or discoverable on server.'
    ).should("be.visible");

    // Renders OCR Failed badge and preserves retry button
    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains(".document-card-ocr-badge.failed", "OCR Failed").should("be.visible");
      cy.contains("button", "Process").should("be.visible").and("not.be.disabled");
    });
  });

  it("surfaces error when document processing API fails (mocked HTTP layer)", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: "doc_10th_fail",
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsForFail");

    cy.intercept("POST", "**/api/v1/documents/doc_10th_fail/process", {
      statusCode: 500,
      body: { detail: "OCR execution timed out after 15 seconds." },
    }).as("processDocFail");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsForFail");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
    });

    cy.wait("@processDocFail");

    cy.contains("Processing failed for \"10th Marksheet\": OCR execution timed out after 15 seconds.").should("be.visible");
    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains(".document-card-ocr-badge.failed", "OCR Failed").should("be.visible");
    });
  });

  it("surfaces error when backend documentId is missing on process click", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: null, // Missing backend id
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsForMissing");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsForMissing");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
    });

    cy.contains("Processing failed for \"10th Marksheet\": Cannot process document: missing backend document identifier.").should("be.visible");
  });

  it("verifies getVerificationStatus rejects on non-success HTTP response and network failure without returning mock data", () => {
    const realToken = "real-authenticated-jwt-token";

    // 1. Missing backend document identifier is rejected safely
    cy.wrap(null).then(async () => {
      let threw = false;
      try {
        await getVerificationStatus("APL-1001", "doc-10th", realToken, null);
      } catch (err) {
        threw = true;
        expect(err.message).to.include("missing backend document identifier");
      }
      expect(threw).to.be.true;
    });

    // 2. Non-success HTTP response (500) does NOT return mock data; throws instead
    cy.intercept("GET", "**/api/v1/documents/doc_backend_500/verification", {
      statusCode: 500,
      body: { detail: "Verification backend internal error" },
    }).as("getVerif500");

    cy.wrap(null).then(async () => {
      let threw = false;
      try {
        await getVerificationStatus("APL-1001", "doc-10th", realToken, "doc_backend_500");
      } catch (err) {
        threw = true;
        expect(err.message).to.include("Verification backend internal error");
      }
      expect(threw).to.be.true;
    });

    // 3. Network failure does NOT return mock data; throws instead
    cy.intercept("GET", "**/api/v1/documents/doc_backend_net_err/verification", {
      forceNetworkError: true,
    }).as("getVerifNetErr");

    cy.wrap(null).then(async () => {
      let threw = false;
      try {
        await getVerificationStatus("APL-1001", "doc-10th", realToken, "doc_backend_net_err");
      } catch (err) {
        threw = true;
        expect(err.message).to.exist;
      }
      expect(threw).to.be.true;
    });
  });

  it("surfaces safe unavailable/error state in Documents UI when verification API fails and does not display mock results", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: "doc_10th_verif_err",
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    const mockProcessingResult = {
      documentId: "doc_10th_verif_err",
      applicationId: "SE20260001",
      documentType: "10TH_MARKSHEET",
      processingState: "COMPLETED",
      engine: "pymupdf+tesseract-ocr",
      pageCount: 1,
      textExtracted: true,
      overallConfidence: 0.91,
      classification: {
        predictedType: "10TH_MARKSHEET",
        confidence: 0.95,
        typeMismatch: false,
      },
      fields: {
        candidateName: { rawValue: "Priya Sharma", normalizedValue: "Priya Sharma", confidence: 0.95 },
        dob: { rawValue: "15/08/2004", normalizedValue: "2004-08-15", confidence: 0.92 },
        percentage: { rawValue: "90.0%", normalizedValue: 90.0, confidence: 0.92 },
      },
    };

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsForVerifFail");

    cy.intercept("POST", "**/api/v1/documents/doc_10th_verif_err/process", {
      statusCode: 200,
      body: mockProcessingResult,
    }).as("processDoc");

    // Intercept verification status with 500 internal server error
    cy.intercept("GET", "**/api/v1/documents/doc_10th_verif_err/verification", {
      statusCode: 500,
      body: { detail: "Verification engine temporarily unavailable." },
    }).as("getVerifStatus500");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsForVerifFail");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
    });

    cy.wait("@processDoc");
    cy.wait("@getVerifStatus500");

    // Open verification details modal
    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "View").click();
    });

    cy.get('[role="dialog"][aria-label="Document Verification"]').within(() => {
      // 1. Content Validation section shows safe unavailable/error state
      cy.contains("Content Validation").should("be.visible");
      cy.contains("Verification details unavailable (network or service error)").should("be.visible");

      // 2. Authoritative Verification section shows safe unavailable state
      cy.contains("Authoritative Verification").should("be.visible");
      cy.contains("Authoritative verification unavailable").should("be.visible");

      // 3. Stale mock validation results ("Format matches requirements") MUST NOT be displayed
      cy.contains("Format matches requirements").should("not.exist");
      // 4. Stale mock authoritative verification ("Verified via DigiLocker/NAD") MUST NOT be displayed
      cy.contains("Verified via Live DigiLocker/NAD").should("not.exist");

      cy.get('button[aria-label="Close dialog"]').click();
    });
  });

  it("displays simulated match label, disclaimer, and 3 distinct sections without displaying verified state", () => {
    const realSession = {
      role: "user",
      name: "Hemanth M.P.",
      email: "hemanth@example.com",
      applicantId: "APL-1001",
      token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.real-applicant-token",
    };

    const mockBackendDocs = [
      {
        id: "doc-10th",
        documentId: "doc_10th_sim_match",
        documentType: "10TH_MARKSHEET",
        name: "10th Marksheet",
        required: true,
        status: "UPLOADED",
        originalFileName: "10th_marksheet.pdf",
        fileName: "10th_marksheet.pdf",
        uploadedAt: "2026-09-05T10:00:00Z",
      },
    ];

    const mockProcessingResult = {
      documentId: "doc_10th_sim_match",
      applicationId: "SE20260001",
      documentType: "10TH_MARKSHEET",
      processingState: "COMPLETED",
      engine: "pymupdf+tesseract-ocr",
      pageCount: 1,
      textExtracted: true,
      overallConfidence: 0.94,
      classification: {
        predictedType: "10TH_MARKSHEET",
        confidence: 0.95,
        typeMismatch: false,
      },
      fields: {
        candidateName: { rawValue: "Hemanth M.P.", normalizedValue: "Hemanth M.P.", confidence: 0.95 },
        registrationNumber: { rawValue: "SYNTH-10TH-12345", normalizedValue: "SYNTH-10TH-12345", confidence: 0.92 },
        dob: { rawValue: "15/05/2000", normalizedValue: "2000-05-15", confidence: 0.92 },
        percentage: { rawValue: "86.5%", normalizedValue: 86.5, confidence: 0.92 },
      },
    };

    const mockVerificationResult = {
      documentId: "doc_10th_sim_match",
      documentType: "10TH_MARKSHEET",
      lifecycleStatus: "VALIDATED",
      processingStatus: "COMPLETED",
      processingConfidence: 0.94,
      validationStatus: "VALIDATED",
      validationResult: {
        documentId: "doc_10th_sim_match",
        documentType: "10TH_MARKSHEET",
        validationStatus: "VALIDATED",
        fieldResults: {
          candidateName: { fieldName: "candidateName", status: "MATCH", extractedValue: "Hemanth M.P.", authoritativeValue: "Hemanth M.P.", confidence: 0.95, message: "Exact name match." },
          percentage: { fieldName: "percentage", status: "MATCH", extractedValue: "86.5", authoritativeValue: "86.5", confidence: 0.92, message: "Percentage matches." },
        },
        reasons: [],
      },
      authoritativeVerification: {
        status: "SIMULATED_MATCH",
        provider: "SyntheticDigiLockerProvider",
        lookupIdentifier: "SYNTH-10TH-12345",
        isSimulated: true,
        disclaimer: "Simulated record for testing/evaluation. Not connected to live DigiLocker/government APIs.",
        message: "Simulated authoritative credential verified via DigiLocker simulation.",
      },
    };

    cy.intercept("GET", "**/api/v1/documents*", {
      statusCode: 200,
      body: mockBackendDocs,
    }).as("getDocsForSim");

    cy.intercept("POST", "**/api/v1/documents/doc_10th_sim_match/process", {
      statusCode: 200,
      body: mockProcessingResult,
    }).as("processDocSim");

    cy.intercept("GET", "**/api/v1/documents/doc_10th_sim_match/verification", {
      statusCode: 200,
      body: mockVerificationResult,
    }).as("getVerifSimMatch");

    cy.visit("/documents", {
      onBeforeLoad(win) {
        win.localStorage.setItem("smartenroll_auth", JSON.stringify(realSession));
      },
    });

    cy.wait("@getDocsForSim");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "Process").click();
    });

    cy.wait("@processDocSim");
    cy.wait("@getVerifSimMatch");

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.contains("button", "View").click();
    });

    cy.get('[role="dialog"][aria-label="Document Verification"]').within(() => {
      // 1. Verify all three distinct sections are present
      cy.contains("h4", "OCR Extraction").should("be.visible");
      cy.contains("h4", "Content Validation").should("be.visible");
      cy.contains("h4", "Authoritative Verification").should("be.visible");

      // 2. SIMULATED_MATCH displays a clearly simulated label
      cy.contains("Simulated Match (Synthetic Fixture Only)").should("be.visible");

      // 3. It DOES NOT display as VERIFIED or as a real DigiLocker/NAD confirmation
      cy.contains("Verified via Live DigiLocker/NAD").should("not.exist");
      cy.contains("Verified via DigiLocker/NAD").should("not.exist");
      cy.get(".status-badge.status-verified").should("not.exist");

      // 4. The disclaimer makes clear that a synthetic fixture result does not establish document authenticity
      cy.contains(
        "Simulated fixture matches are synthetic evaluation aids only and do not establish document authenticity."
      ).should("be.visible");

      cy.get('button[aria-label="Close dialog"]').click();
    });
  });
});
