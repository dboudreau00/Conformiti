// `npm run shots` — regenerate the README screenshots from the running app.
//
// The screenshot project writes PNGs into assets/screenshots/, so it is gated
// behind SHOOT rather than left in the default project list where `npm test`
// (or a bare `npx playwright test`) would rewrite the repository as a side
// effect. A launcher rather than an inline npm script because `VAR=1 cmd` is
// not portable to Windows.
//
// Playwright's CLI is invoked through node directly: spawning `npx` adds a
// shell layer that swallows the child's output and exit code on Windows.
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

// The package does not export ./cli.js, so resolve it from the manifest rather
// than by subpath.
const require = createRequire(import.meta.url);
const manifest = require("@playwright/test/package.json");
const cli = path.join(path.dirname(require.resolve("@playwright/test/package.json")),
                      manifest.bin.playwright);

const result = spawnSync(
  process.execPath,
  [cli, "test", "--project=screenshots", ...process.argv.slice(2)],
  { stdio: "inherit", env: { ...process.env, SHOOT: "1" } }
);
process.exit(result.status ?? 1);
