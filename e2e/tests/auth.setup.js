import { test as setup, expect } from "@playwright/test";
import { DEMO, signIn } from "../fixtures.js";

const ADMIN_STATE = "./.auth/admin.json";

// Runs once, before every other project. Signs in as the demo administrator
// and stores the session so the rest of the suite starts authenticated.
setup("authenticate as the administrator", async ({ page }) => {
  await signIn(page, DEMO.admin);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.context().storageState({ path: ADMIN_STATE });
});
