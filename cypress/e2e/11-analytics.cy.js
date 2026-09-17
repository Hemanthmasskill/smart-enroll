describe("Smart Enroll - Analytics", () => {
  beforeEach(() => {
    cy.visitAsAdmin("/admin/analytics");
  });

  it("shows prototype analytics derived from the demo dataset", () => {
    cy.contains("h1, h2", "Admission Analytics").should("be.visible");
    cy.contains("Prototype analytics computed from the current demo dataset.").should("be.visible");

    cy.contains("Total Applications").should("be.visible");
    cy.contains("Processing Complete Rate").should("be.visible");
    cy.contains("Total Exceptions").should("be.visible");
    cy.contains("Open Exceptions").should("be.visible");
  });

  it("shows all six analytics distributions", () => {
    [
      "Applications by Workflow Status",
      "Eligibility Distribution",
      "Document Verification Distribution",
      "Programme-wise Applications",
      "Exception Severity",
      "Exception Status",
    ].forEach((heading) => cy.contains(heading).should("be.visible"));

    cy.get(".analytics-grid .admin-panel").should("have.length", 6);
    cy.get(".bar-fill").its("length").should("be.greaterThan", 0);
  });

  it("clearly labels analytics as prototype/demo data", () => {
    cy.contains("prototype/demo data for illustration only").should("be.visible");
    cy.contains("replaced by live processing metrics once the backend is connected").should("be.visible");
  });
});
