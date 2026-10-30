// A launcher because `VAR=1 cmd` is not portable to Windows: it sets SHOOT, which gates the project that writes PNGs.
// Run through node, not npx: on Windows the npx shell layer swallows the child's output and exit code.
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

// The package does not export ./cli.js: resolve it from the manifest, not by subpath.
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
