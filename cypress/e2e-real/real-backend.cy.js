describe("Smart Enroll - Real Backend E2E Test Suite (Zero Intercepts)", () => {
  const timestamp = Date.now();
  const testUser = {
    fullName: `E2E Live User ${timestamp}`,
    email: `e2e.live.${timestamp}@smartenroll.smoke`,
    mobile: "9876543210",
    dob: "2000-01-15",
    password: "StrongPassword123!",
  };

  it("1. Registers a new applicant through the real browser UI and backend", () => {
    cy.visit("/register");
    cy.contains("Create your applicant account").should("be.visible");

    cy.get("#fullName").type(testUser.fullName);
    cy.get("#email").type(testUser.email);
    cy.get("#mobile").type(testUser.mobile);
    cy.get("#dob").type(testUser.dob);
    cy.get("#password").type(testUser.password);
    cy.get("#confirmPassword").type(testUser.password);
    cy.get('input[type="checkbox"]').check();

    cy.get('button[type="submit"]').click();

    // Browser navigates to /dashboard on successful live registration
    cy.url({ timeout: 10000 }).should("include", "/dashboard");
    cy.contains(testUser.fullName).should("be.visible");
  });

  it("2. Logs in using real backend authentication through the browser", () => {
    // Clear session to test explicit login
    cy.clearLocalStorage();
    cy.visit("/login");

    cy.contains(".role-toggle button", "User").click();
    cy.get("#email").type(testUser.email);
    cy.get("#password").type(testUser.password);
    cy.get('button[type="submit"]').click();

    cy.url({ timeout: 10000 }).should("include", "/dashboard");
    cy.contains(testUser.fullName).should("be.visible");
  });

  it("3. Creates, submits, and views an admission application through the real backend", () => {
    // Ensure logged in
    cy.visit("/login");
    cy.contains(".role-toggle button", "User").click();
    cy.get("#email").type(testUser.email);
    cy.get("#password").type(testUser.password);
    cy.get('button[type="submit"]').click();
    cy.url().should("include", "/dashboard");

    cy.visit("/application");
    cy.contains("Admission Application").should("be.visible");

    // Step 1 - Personal Details
    cy.get("#fullName").clear().type(testUser.fullName);
    cy.get("#dob").clear().type(testUser.dob);
    cy.get("#gender").select("Male");
    cy.get("#nationality").clear().type("Indian");
    cy.contains("button", "Next").click();

    // Step 2 - Contact Details
    cy.get("#email").clear().type(testUser.email);
    cy.get("#mobile").clear().type(testUser.mobile);
    cy.get("#address").clear().type("789 Real Backend Blvd");
    cy.get("#city").clear().type("Chennai");
    cy.get("#state").clear().type("Tamil Nadu");
    cy.get("#pinCode").clear().type("600048");
    cy.contains("button", "Next").click();

    // Step 3 - Academic Details
    cy.get("#tenthBoard").type("CBSE");
    cy.get("#tenthPercentage").type("88.5");
    cy.get("#twelfthBoard").type("State Board");
    cy.get("#twelfthPercentage").type("91.0");
    cy.get("#ugDegree").type("BCA");
    cy.get("#university").type("Madras University");
    cy.get("#graduationYear").type("2024");
    cy.get("#cgpa").type("8.8");
    cy.contains("button", "Next").click();

    // Step 4 - Programme Selection
    cy.get("#programmeId").select("mca");
    cy.contains("button", "Next").click();

    // Step 5 - Review & Submit
    cy.contains("Review & Submit").should("be.visible");
    cy.contains("MCA — Master of Computer Applications").should("be.visible");
    cy.contains("button", "Submit Application").click();

    cy.contains("Application submitted", { timeout: 10000 }).should("be.visible");
    cy.contains("button", "Go to Dashboard").click();

    cy.url({ timeout: 10000 }).should("include", "/dashboard");
    cy.contains("MCA").should("be.visible");
  });

  it("4. Uploads and lists a document through the real backend", () => {
    // Ensure logged in
    cy.visit("/login");
    cy.contains(".role-toggle button", "User").click();
    cy.get("#email").type(testUser.email);
    cy.get("#password").type(testUser.password);
    cy.get('button[type="submit"]').click();
    cy.url().should("include", "/dashboard");

    cy.visit("/documents");
    cy.contains("h1", "Documents").should("be.visible");

    // Minimal valid PDF binary
    const pdfContent = "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000053 00000 n \n0000000102 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n178\n%%EOF\n";

    cy.contains(".document-card", "10th Marksheet").within(() => {
      cy.get('input[type="file"]').selectFile(
        {
          contents: Cypress.Buffer.from(pdfContent),
          fileName: "e2e_real_10th_marksheet.pdf",
          mimeType: "application/pdf",
        },
        { force: true }
      );
      cy.contains("e2e_real_10th_marksheet.pdf", { timeout: 10000 }).should("be.visible");
      cy.contains("Uploaded").should("be.visible");
    });
  });

  it("5. Admin logs in and views applications & agent activity from real backend", () => {
    cy.clearLocalStorage();
    cy.visit("/login");

    cy.contains(".role-toggle button", "Admin").click();
    cy.get("#email").type("admin@smartenroll.edu");
    cy.get("#password").type("AdminPassword123!");
    cy.get('button[type="submit"]').click();

    cy.url({ timeout: 10000 }).should("include", "/admin");

    // Inspect Applications view
    cy.visit("/admin/applications");
    cy.contains("h1", "Applications").should("be.visible");
    cy.contains(testUser.fullName, { timeout: 10000 }).should("be.visible");

    // Inspect Agent Activity view
    cy.visit("/admin/agent-activity");
    cy.contains("h1, h2", "Agent Activity").should("be.visible");
    cy.contains("OBSERVE → PLAN → ACT → VERIFY → RE-PLAN").should("be.visible");
  });
});
