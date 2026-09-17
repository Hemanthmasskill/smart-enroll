const AUTH_KEY = "smartenroll_auth";

const applicantSession = {
  role: "user",
  name: "Hemanth M.P.",
  email: "hemanth@example.com",
  applicantId: "APL-1001",
  token: "mock-jwt-token",
};

const adminSession = {
  role: "admin",
  name: "Admin User",
  email: "admin@example.com",
  applicantId: null,
  token: "mock-jwt-token",
};

function visitWithSession(path, session) {
  cy.visit(path, {
    onBeforeLoad(win) {
      win.localStorage.setItem(AUTH_KEY, JSON.stringify(session));
    },
  });
}

Cypress.Commands.add("visitAsApplicant", (path = "/dashboard") => {
  visitWithSession(path, applicantSession);
});

Cypress.Commands.add("visitAsAdmin", (path = "/admin") => {
  visitWithSession(path, adminSession);
});

Cypress.Commands.add("clearSmartEnrollSession", () => {
  cy.window().then((win) => {
    win.localStorage.removeItem(AUTH_KEY);
  });
});
