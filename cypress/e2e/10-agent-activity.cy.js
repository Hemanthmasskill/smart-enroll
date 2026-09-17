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
});
