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
});
