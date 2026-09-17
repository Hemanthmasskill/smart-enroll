describe("Smart Enroll - Eligibility and Application Status", () => {
  it("shows deterministic eligibility evaluation as pending", () => {
    cy.visitAsApplicant("/eligibility");

    cy.contains("Eligibility Status").should("be.visible");
    cy.contains("MCA — Master of Computer Applications").should("be.visible");
    cy.contains("Eligibility Evaluation Pending").should("be.visible");
    cy.contains("Bachelor's Degree").should("be.visible");
    cy.contains("Minimum Percentage").should("be.visible");
    cy.contains("Mathematics Requirement").should("be.visible");
    cy.contains("Required Documents").should("be.visible");
    cy.contains("Entrance Requirement").should("be.visible");
    cy.contains("it does not invent, infer, or adjust admission criteria").should("be.visible");
  });

  it("shows the current application processing timeline", () => {
    cy.visitAsApplicant("/status");

    cy.contains("Application Status").should("be.visible");
    cy.contains("SE20260001").should("be.visible");
    cy.contains("Waiting for Documents").should("be.visible");
    cy.contains("Processing Timeline").should("be.visible");
    cy.contains("Application Created").should("be.visible");
    cy.contains("Application Submitted").should("be.visible");
    cy.contains("Documents Received").should("be.visible");
    cy.contains("Document Verification").should("be.visible");
    cy.contains("Eligibility Evaluation").should("be.visible");
    cy.contains("Applicant Action Required").should("be.visible");
    cy.contains("2 documents are still required.").should("be.visible");
  });
});
