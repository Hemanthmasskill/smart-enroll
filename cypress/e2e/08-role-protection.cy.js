describe("Smart Enroll - Role Protection", () => {
  it("redirects a logged-out user away from applicant routes", () => {
    cy.clearAllLocalStorage();
    cy.visit("/documents");
    cy.location("pathname").should("eq", "/login");
  });

  it("redirects a logged-out user away from admin routes", () => {
    cy.clearAllLocalStorage();
    cy.visit("/admin/applications");
    cy.location("pathname").should("eq", "/login");
  });

  it("prevents an applicant from entering admin routes", () => {
    cy.visitAsApplicant("/admin");
    cy.location("pathname").should("eq", "/dashboard");
    cy.contains("Welcome, Hemanth").should("be.visible");
  });

  it("prevents an administrator from entering applicant routes", () => {
    cy.visitAsAdmin("/documents");
    cy.location("pathname").should("eq", "/admin");
    cy.contains("Admin Dashboard").should("be.visible");
  });
});
