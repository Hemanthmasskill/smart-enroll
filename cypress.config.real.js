import { defineConfig } from "cypress";

export default defineConfig({
  e2e: {
    baseUrl: "http://localhost:5173",
    defaultCommandTimeout: 10000,
    viewportWidth: 1280,
    viewportHeight: 800,
    video: false,
    screenshotOnRunFailure: true,
    specPattern: "cypress/e2e-real/**/*.cy.{js,jsx,ts,tsx}",

    setupNodeEvents(on, config) {
      // Reserved for future reporting hooks.
    },
  },
});
