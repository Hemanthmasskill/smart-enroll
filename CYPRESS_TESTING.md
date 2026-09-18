# Smart Enroll Cypress Regression Suite

This suite covers the stable frontend through Increment 5.

## Before running tests

Start the Vite app in Terminal 1:

```powershell
cd C:\Users\Hemanth\smart-enroll
npm run dev
```

Leave it running at `http://localhost:5173`.

## Run all tests automatically

Open Terminal 2 in the same project and run:

```powershell
npm run cy:run
```

Equivalent command:

```powershell
npx cypress run
```

## Open the visual Cypress runner

```powershell
npm run cy:open
```

## Specs

- `01-auth.cy.js` — public landing page, applicant login/logout, admin login/logout
- `02-applicant.cy.js` — dashboard, five-step application form, profile update
- `03-documents.cy.js` — document state, three-layer verification, upload/remove
- `04-digilocker.cy.js` — simulated DigiLocker connection and record use
- `05-eligibility-status.cy.js` — deterministic eligibility and processing timeline
- `06-notifications.cy.js` — unread state and mark-all-read
- `07-admin.cy.js` — admin dashboard, applications/details, exceptions/filtering
- `08-role-protection.cy.js` — logged-out and cross-role route protection

The custom commands in `cypress/support/commands.js` create mock applicant/admin sessions directly in localStorage for tests that do not need to exercise the login UI. This keeps the regression suite fast while `01-auth.cy.js` still tests the real login workflow.

After Increment 6 is integrated, rerun the entire suite before adding Increment 6-specific specs for Programme Rules, Agent Activity, and Analytics.

## Increment 7 integration coverage

`12-increment7-integration.cy.js` adds 5 end-to-end checks for the frontend freeze candidate:

- integrated observable 8-stage admission workflow
- document upload -> dashboard count/next-action synchronization
- simulated DigiLocker record -> document verification synchronization
- notification read state -> dashboard unread-count synchronization
- applicant/admin workflow consistency for the main demo application

Expected cumulative result after Increment 7: **12 specs / 34 tests**.
