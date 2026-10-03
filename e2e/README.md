# End-to-end browser tests

Playwright tests that drive the **built** application in a real browser: sign
in, load every screen, exercise the control register, the folder tree, the risk
register, an access review, the audit trail, passkeys, evidence packages and
their request list, vendors and the public questionnaire, and the theme
system, then sign out.

They live outside `frontend/` on purpose, so Playwright never enters the
application's dependency tree or its `npm audit`.

## Run them

```bash
cd e2e
npm install
npx playwright install chromium
npm test
```

That is the whole setup. Playwright starts everything it needs:

1. deletes `e2e/.e2e-db.sqlite3`, `e2e/.e2e-media` and `e2e/.e2e-tree`, then
   migrates, seeds the three control libraries and loads the demo dataset into
   them (your own development database and uploads are never touched);
2. starts Django on `127.0.0.1:8001`;
3. runs `npm run build` in `frontend/` and serves the result with
   `vite preview` on `127.0.0.1:4173`, proxying `/api` and `/media` to Django.

Every run starts from an empty database, so a second run behaves exactly like
the first.

The backend runs with DEBUG on, non-Secure cookies, and the sign-in, MFA,
anonymous and questionnaire throttles raised to 1000 a minute, so the suite
does not test those limits. It uses the header transport unless
`E2E_TRANSPORT=cookie` is set; `E2E_TRANSPORT=cookie npm test` (in PowerShell,
set `$env:E2E_TRANSPORT = "cookie"` first) runs it the way a default
installation signs in, and CI runs both.

Prerequisites: the repo-root `.venv` (created by `install.sh` / `install.ps1`)
and `frontend/node_modules`.

| Command | What it does |
|---|---|
| `npm test` | The whole suite, headless. |
| `npm run test:headed` | The same, with a visible browser. |
| `npx playwright test controls` | One spec. |
| `npx playwright test --debug` | Step through with the inspector. |
| `npm run report` | Open the HTML report from the last run. |
| `npm run shots` | Regenerate the README screenshots (writes to `assets/screenshots/`). |

## What makes a test fail

Beyond its own assertions, **any console error, uncaught exception or failed
request fails the test**. This catches real defects: the audit-log filter
listing every action once per row, and four screens reading only the first
page of a paginated endpoint, first showed up as console noise during a
screenshot run.

A test that deliberately provokes an error response says so by pattern:

```js
expectBrowserError(page, /status of 400/);
```

There is no switch that turns the check off.

## Writing a test

- Import `test` and `expect` from `../fixtures.js`, never from
  `@playwright/test`: that is where the console-error fixture lives.
- Use `open(page, "/risks", "Risk register")` to navigate: it waits for the
  page's `<h1>`, the title at the top of `<main>`. Several screens repeat their
  title as a panel `<h2>`, so an unscoped `getByRole("heading")` is ambiguous.
- The top bar keeps most of the navigation in menus. Use `await navLink(page, "/risks")`
  to get a link by route: it opens the Governance menu first for a Governance
  page, the account menu for `/settings`, and returns the link. `signOut(page)`
  does the same for Sign out. Matching a menu button by its name is by prefix
  (`governanceButton`, `accountButton`, `appearanceButton`), because the name
  carries state such as the page you are on.
- Prefer roles and accessible names over CSS. Where a name is missing, that is
  usually worth fixing in the application instead.
- Watch for text that Tailwind uppercases: the DOM says `login` while the
  screen says `LOGIN`. Match case-insensitively, and scope to the table: the
  same strings sit in hidden `<option>` elements of the filter dropdowns.

## In CI

The `e2e` job in `.github/workflows/ci.yml` runs the suite twice (once per
authentication transport) on every push to `main` and every pull request, with
the browser binary cached by Playwright version. On failure it uploads the
HTML report and the traces; open one with:

```bash
npx playwright show-trace path/to/trace.zip
```

## Layout

```
e2e/
  playwright.config.js    servers, projects, the hermetic database reset
  fixtures.js             console-error fixture, personas, navigation helpers
  shots.mjs               runs the screenshot project (npm run shots)
  tests/
    auth.setup.js         signs in once; the other projects reuse the session
    auth.spec.js          sign-in, sign-out, token revocation, every persona
    shell.spec.js         every route renders; the top bar, its Governance, account and
                          Appearance menus; the auditor's bar; the notification tray
    search.spec.js        the Ctrl K palette: results by role, Enter lands on the record
    workspace.spec.js     dashboard (lead schedule, coverage atlas, calendar, review
                          queue), documents, risks
    controls.spec.js      217-control register: tabs, filters, search, export
    governance.spec.js    audit trail, access reviews, users, meetings, groups
    downloads.spec.js     a download or export that fails says why on screen
    settings.spec.js      profile, theme packs, accent packs, MFA enrolment
    laptop.spec.js        a 1366 by 768 laptop and a 1024 wide window: tables, the
                          dashboard and the top bar stay on screen
    phone.spec.js         a 390 by 844 phone: the Menu sheet, menus that fit the screen
    packages.spec.js      evidence packages: digest, export, auditor, samples
    passkeys.spec.js      passkey enrolment and sign-in (virtual authenticator)
    pbc.spec.js           the PBC request list: organisation, auditor, assignee
    questionnaire.spec.js the vendor questionnaire, answered by link
    vendors.spec.js       vendor register, assurance, responsibility matrix
    viewer.spec.js        the in-browser document viewer
    screenshots.spec.js   opt-in: regenerates the README screenshots
```
