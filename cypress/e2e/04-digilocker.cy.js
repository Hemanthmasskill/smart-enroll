describe("Smart Enroll - DigiLocker Simulation", () => {
  it("connects the simulated DigiLocker flow and uses a verified record", () => {
    cy.visitAsApplicant("/digilocker");

    cy.contains("Verify Academic Records with DigiLocker").should("be.visible");
    cy.contains("frontend simulation only").should("be.visible");
    cy.contains("button", "Connect DigiLocker").click();

    cy.contains("DigiLocker Connected", { timeout: 5000 }).should("be.visible");
    cy.contains("Academic Records Found").should("be.visible");
    cy.contains("Degree Certificate").should("be.visible");
    cy.contains("button", "Use Verified Record").click();
    cy.contains("button", "Record in Use").should("be.disabled");

    cy.contains("button", "Back to Documents").click();
    cy.location("pathname").should("eq", "/documents");
  });
});
