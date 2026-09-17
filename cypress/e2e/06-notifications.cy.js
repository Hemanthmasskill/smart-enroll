describe("Smart Enroll - Notifications", () => {
  it("shows the expected unread notifications and can mark all as read", () => {
    cy.visitAsApplicant("/notifications");

    cy.contains("Notifications").should("be.visible");
    cy.contains("3 unread notifications").should("be.visible");
    cy.contains("Degree Certificate verification in progress").should("be.visible");
    cy.contains("Transfer Certificate required").should("be.visible");
    cy.contains("Government ID required").should("be.visible");

    cy.contains("button", "Mark All as Read").click();
    cy.contains("You're all caught up.", { timeout: 3000 }).should("be.visible");
    cy.contains("button", "Mark All as Read").should("not.exist");
  });
});
