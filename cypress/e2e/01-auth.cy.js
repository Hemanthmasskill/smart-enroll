describe("Smart Enroll - Authentication", () => {
  beforeEach(() => {
    cy.clearAllLocalStorage();
  });

  it("opens the landing page", () => {
    cy.visit("/");
    cy.contains("Smart Enroll").should("be.visible");
    cy.contains("Smarter admissions.").should("be.visible");
    cy.contains("Login").should("be.visible");
  });

  it("allows an applicant to log in and log out", () => {
    cy.visit("/login");
    cy.get('[role="tab"][aria-selected="true"]').should("contain", "User");
    cy.get("#email").type("applicant@example.com");
    cy.get("#password").type("password123");
    cy.contains("button", "Login as User").click();

    cy.url().should("include", "/dashboard");
    cy.contains("Welcome, Hemanth").should("be.visible");

    cy.contains("button", "Logout").click();
    cy.location("pathname").should("eq", "/");
  });

  it("allows an administrator to log in and log out", () => {
    cy.visit("/login");
    cy.contains('[role="tab"]', "Admin").click();
    cy.get('[role="tab"][aria-selected="true"]').should("contain", "Admin");
    cy.get("#email").type("admin@example.com");
    cy.get("#password").type("password123");
    cy.contains("button", "Login as Admin").click();

    cy.location("pathname").should("eq", "/admin");
    cy.contains("Admin Dashboard").should("be.visible");

    cy.contains("button", "Logout").click();
    cy.location("pathname").should("eq", "/");
  });
});
