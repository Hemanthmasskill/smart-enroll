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
});
