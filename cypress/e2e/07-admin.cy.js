describe("Smart Enroll - Admin Portal", () => {
  it("shows dashboard statistics and monitoring panels", () => {
    cy.visitAsAdmin("/admin");

    cy.contains("Admin Dashboard").should("be.visible");
    cy.contains("Total Applications").should("be.visible");
    cy.contains("Processing").should("be.visible");
    cy.contains("Waiting for Documents").should("be.visible");
    cy.contains("Eligible").should("be.visible");
    cy.contains("Open Exceptions").should("be.visible");
    cy.contains("Recent Applications").should("be.visible");
    cy.contains("Attention Required").should("be.visible");
  });

  it("filters applications and opens the main demo application", () => {
    cy.visitAsAdmin("/admin/applications");

    cy.contains("Applications").should("be.visible");
    cy.get('input[placeholder="Search application ID or applicant"]').type("Hemanth");
    cy.contains("SE20260001").should("be.visible");
    cy.contains("Aisha Rahman").should("not.exist");

    cy.contains("button", "View Details").click();
    cy.location("pathname").should("eq", "/admin/applications/SE20260001");
    cy.contains("Hemanth M.P.").should("be.visible");
    cy.contains("Documents & Verification").should("be.visible");
    cy.contains("Processing Timeline").should("be.visible");
    cy.contains("Exceptions").should("be.visible");
    cy.contains("Transfer Certificate and Government ID have not been submitted.").should("be.visible");
    cy.contains("button", /Approve|Reject/i).should("not.exist");
  });

  it("filters exceptions by severity", () => {
    cy.visitAsAdmin("/admin/exceptions");

    cy.contains("Exceptions").should("be.visible");
    cy.get(".admin-controls select").eq(1).select("HIGH");
    cy.contains("Priya N").should("be.visible");
    cy.contains("CROSS DOCUMENT MISMATCH").should("be.visible");
    cy.contains("Hemanth M.P.").should("not.exist");
    cy.contains("Admission decisions are not manually approved or rejected").should("be.visible");
  });
});
