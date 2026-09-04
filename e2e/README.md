# End-to-end browser tests

Playwright tests that drive the **built** application in a real browser: sign
in, load every screen, exercise the control register, the folder tree, the risk
register, an access review, the audit trail and the theme system, then sign
out.

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

1. deletes `e2e/.e2e-db.sqlite3` and `e2e/.e2e-media`, then migrates, seeds the
   three control libraries and loads the demo dataset into them — your own
   development database and uploads are never touched;
2. starts Django on `127.0.0.1:8001`;
3. runs `npm run build` in `frontend/` and serves the result with
   `vite preview` on `127.0.0.1:4173`, proxying `/api` and `/media` to Django.

Every run starts from an empty database, so a second run behaves exactly like
the first.

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
request fails the test**. That is not decoration: two real 0.2.0 defects — the
audit-log filter listing every action once per row, and four screens silently
reading only the first page of a paginated endpoint — first showed up as
console noise during a screenshot run.

A test that deliberately provokes an error response says so by pattern:

```js
expectBrowserError(page, /status of 400/);
```

There is no switch that turns the check off.

## Writing a test

- Import `test` and `expect` from `../fixtures.js`, never from
  `@playwright/test` — that is where the console-error fixture lives.
- Use `open(page, "/risks", "Risk register")` to navigate: it waits for the
  top-bar `<h1>`. Several screens repeat their title as a panel `<h2>`, so an
  unscoped `getByRole("heading")` is ambiguous.
- Prefer roles and accessible names over CSS. Where a name is missing, that is
  usually worth fixing in the application instead.
- Watch for text that Tailwind uppercases: the DOM says `login` while the
  screen says `LOGIN`. Match case-insensitively, and scope to the table — the
  same strings sit in hidden `<option>` elements of the filter dropdowns.

## In CI

The `e2e` job in `.github/workflows/ci.yml` runs the suite on every push and
pull request, with the browser binary cached by Playwright version. On failure
it uploads the HTML report and the traces; open one with:

```bash
npx playwright show-trace path/to/trace.zip
```

## Layout

```
e2e/
  playwright.config.js  servers, projects, the hermetic database reset
  fixtures.js           the console-error fixture, personas, navigation helpers
  tests/
    auth.setup.js       signs in once; the other projects reuse the session
    auth.spec.js        sign-in, sign-out, token revocation, every persona
    shell.spec.js       every route renders; navigation; the notification tray
    workspace.spec.js   dashboard, calendar, review queue, documents, risks
    controls.spec.js    the 217-control register: tabs, filters, search, export
    governance.spec.js  audit trail, access reviews, users, meetings, groups
    settings.spec.js    profile, theme packs, accent packs, MFA enrolment
    screenshots.spec.js opt-in: regenerates the README screenshots
```
