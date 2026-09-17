describe("Smart Enroll - Programme Rules", () => {
  beforeEach(() => {
    cy.visitAsAdmin("/admin/programs");
  });

  it("shows deterministic programme rules for all configured programmes", () => {
    cy.contains("h1, h2", "Programme Rules").should("be.visible");
    cy.contains("not generated, inferred, or modified by the Smart Enroll agent").should("be.visible");

    cy.contains("MCA").should("be.visible");
    cy.contains("MBA").should("be.visible");
    cy.contains("M.Sc Computer Science").should("be.visible");
    cy.contains("M.Tech Computer Science").should("be.visible");
    cy.contains("Minimum Bachelor's Percentage").should("be.visible");
  });

  it("edits and saves the MCA minimum percentage in the frontend simulation", () => {
    cy.contains("section", "MCA").within(() => {
      cy.contains("button", "Edit").click();
      cy.get("#mca-minimumPercentage").clear().type("51%");
      cy.contains("button", "Save Changes").click();
      cy.contains("51%").should("be.visible");
    });
  });

  it("can cancel an edit without changing the displayed rule", () => {
    cy.contains("section", "MCA").within(() => {
      cy.contains("50%").should("be.visible");
      cy.contains("button", "Edit").click();
      cy.get("#mca-minimumPercentage").clear().type("99%");
      cy.contains("button", "Cancel").click();
      cy.contains("50%").should("be.visible");
    });
  });
});
