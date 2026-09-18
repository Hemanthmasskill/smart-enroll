describe("Smart Enroll - Increment 7 Frontend Integration", () => {
  it("shows the integrated observable workflow with the established baseline state", () => {
    cy.visitAsApplicant("/status");

    cy.contains("Admission Processing Workflow").should("be.visible");
    cy.contains("OBSERVE → PLAN → ACT → VERIFY → RE-PLAN").should("be.visible");

    cy.contains(".workflow-stage", "Application Submitted").within(() => {
      cy.contains("Completed").should("be.visible");
    });
    cy.contains(".workflow-stage", "Document Check").within(() => {
      cy.contains("Action Required").should("be.visible");
      cy.contains("2 required documents are still missing.").should("be.visible");
    });
    cy.contains(".workflow-stage", "OCR Extraction").within(() => {
      cy.contains("Completed").should("be.visible");
    });
    cy.contains(".workflow-stage", "Authoritative Verification").within(() => {
      cy.contains("In Progress").should("be.visible");
    });
    cy.contains("private model reasoning or chain-of-thought").should("be.visible");
  });

  it("synchronizes a document upload with dashboard counts and next action", () => {
    cy.visitAsApplicant("/documents");

    cy.contains(".document-card", "Transfer Certificate").within(() => {
      cy.get('input[type="file"]').selectFile(
        {
          contents: Cypress.Buffer.from("Increment 7 transfer certificate"),
          fileName: "transfer_increment7.pdf",
          mimeType: "application/pdf",
        },
        { force: true }
      );
    });

    cy.contains("Transfer Certificate uploaded. Application state has been recalculated.", {
      timeout: 4000,
    }).should("be.visible");

    cy.contains("a", "Dashboard").click();
    cy.location("pathname").should("eq", "/dashboard");
    cy.contains("5 of 6 Submitted").should("be.visible");
    cy.contains("1 document is still required.").should("be.visible");
    cy.contains("50% Complete").should("be.visible");
  });

  it("links a simulated DigiLocker record back to document verification state", () => {
    cy.visitAsApplicant("/digilocker");

    cy.contains("button", "Connect DigiLocker").click();
    cy.contains("button", "Use Verified Record", { timeout: 5000 }).click();
    cy.contains("Degree / Provisional Certificate is now authoritatively verified", {
      timeout: 4000,
    }).should("be.visible");

    cy.contains("button", "Back to Documents").click();
    cy.contains(".document-card", "Degree / Provisional Certificate").within(() => {
      cy.contains("Verified").should("be.visible");
    });
  });

  it("synchronizes notification read state back to the dashboard", () => {
    cy.visitAsApplicant("/notifications");
    cy.contains("button", "Mark All as Read").click();
    cy.contains("Dashboard unread count is now synchronized.", { timeout: 3000 }).should("be.visible");

    cy.contains("a", "Dashboard").click();
    cy.contains("0 New").should("be.visible");
  });

  it("shows the same workflow state in the admin application details view", () => {
    cy.visitAsAdmin("/admin/applications/SE20260001");

    cy.contains("Admission Processing Workflow").should("be.visible");
    cy.contains(".workflow-stage", "Document Check").within(() => {
      cy.contains("Action Required").should("be.visible");
    });
    cy.contains("Prototype boundary").should("be.visible");
    cy.contains("button", /Approve|Reject/i).should("not.exist");
  });
});
