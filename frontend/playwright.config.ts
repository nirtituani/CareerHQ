import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright runs against the stack that is already running — it does not
 * start one. The tests exercise the proxy, the backend, and the database
 * together, which is the point: a smoke test against a mocked backend proves
 * nothing that the unit tests do not already prove.
 */
// 127.0.0.1 rather than localhost: Node resolves localhost to ::1 first, while
// Docker publishes ports on IPv4 only — which surfaces as ECONNREFUSED ::1:3000
// against a stack that is demonstrably running.
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
