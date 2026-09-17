describe("Smart Enroll - Applicant Core Workflow", () => {
  it("shows the applicant dashboard with the established demo state", () => {
    cy.visitAsApplicant("/dashboard");

    cy.contains("Welcome, Hemanth").should("be.visible");
    cy.contains("Waiting for Documents").should("be.visible");
    cy.contains("45% Complete").should("be.visible");
    cy.contains("4 of 6 Submitted").should("be.visible");
    cy.contains("Pending").should("be.visible");
    cy.contains("3 New").should("be.visible");
    cy.contains("2 documents are still required.").should("be.visible");
  });

  it("completes the five-step application form and submits it", () => {
    cy.visitAsApplicant("/application");
    cy.contains("Admission Application").should("be.visible");

    // Step 1 - Personal Details
    cy.get("#fullName").type("Hemanth M.P.");
    cy.get("#dob").type("2001-06-14");
    cy.get("#gender").select("Male");
    cy.get("#nationality").type("Indian");
    cy.contains("button", "Next").click();

    // Step 2 - Contact Details
    cy.get("#email").type("hemanth@example.com");
    cy.get("#mobile").type("9876543210");
    cy.get("#address").type("12 Demo Street");
    cy.get("#city").type("Chennai");
    cy.get("#state").type("Tamil Nadu");
    cy.get("#pinCode").type("600001");
    cy.contains("button", "Next").click();

    // Step 3 - Academic Details
    cy.get("#tenthBoard").type("State Board");
    cy.get("#tenthPercentage").type("88");
    cy.get("#twelfthBoard").type("State Board");
    cy.get("#twelfthPercentage").type("84");
    cy.get("#ugDegree").type("B.Sc Computer Science");
    cy.get("#university").type("Example University");
    cy.get("#graduationYear").type("2025");
    cy.get("#cgpa").type("7.8");
    cy.contains("button", "Next").click();

    // Step 4 - Programme
    cy.get("#programmeId").select("mca");
    cy.contains("button", "Next").click();

    // Step 5 - Review & Submit
    cy.contains("Review & Submit").should("be.visible");
    cy.contains("B.Sc Computer Science").should("be.visible");
    cy.contains("MCA — Master of Computer Applications").should("be.visible");
    cy.contains("button", "Submit Application").click();

    cy.contains("Application submitted", { timeout: 5000 }).should("be.visible");
    cy.contains("Go to Dashboard").should("be.visible");
  });

  it("loads the applicant profile and updates contact details", () => {
    cy.visitAsApplicant("/profile");

    cy.contains("Profile").should("be.visible");
    cy.contains("APL-1001").should("be.visible");
    cy.contains("Hemanth M.P.").should("be.visible");

    cy.contains("button", "Edit Contact Details").click();
    cy.get('.profile-edit-field input').eq(0).clear().type("updated@example.com");
    cy.get('.profile-edit-field input').eq(1).clear().type("9123456789");
    cy.contains("button", "Save Changes").click();

    cy.contains("Contact details updated.", { timeout: 3000 }).should("be.visible");
    cy.contains("updated@example.com").should("be.visible");
    cy.contains("9123456789").should("be.visible");
  });
});
