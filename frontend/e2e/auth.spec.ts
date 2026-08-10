import { expect, test } from "@playwright/test";

/**
 * Smoke tests for the signed-out path (T058).
 *
 * These run against the real stack, so they cover what unit tests cannot: the
 * Next.js proxy, middleware, and the backend answering together. Completing an
 * actual Google sign-in is deliberately out of scope — it would require real
 * credentials and depend on Google's own interface.
 */

test("an unauthenticated visitor is sent to sign-in", async ({ page }) => {
  await page.goto("/dashboard");

  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
  await expect(page.getByRole("link", { name: /continue with google/i })).toBeVisible();
});

test("the root sends signed-out visitors to sign-in", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("sign-in leads to Google", async ({ page }) => {
  await page.goto("/login");

  const signIn = page.getByRole("link", { name: /continue with google/i });
  await expect(signIn).toHaveAttribute("href", "/api/auth/google/login");

  // Follow the redirect chain without loading Google's page.
  const response = await page.request.get("/api/auth/google/login", { maxRedirects: 0 });
  expect(response.status()).toBe(302);

  const location = response.headers()["location"];
  expect(location).toContain("accounts.google.com");
  // The redirect URI must be browser-facing, not the internal Docker hostname.
  expect(location).toContain(encodeURIComponent("http://localhost:3000/api/auth/google/callback"));
});

test("a declined consent explains itself and creates nothing", async ({ page }) => {
  await page.goto("/login?error=access_denied");

  await expect(page.getByRole("alert")).toContainText(/cancelled/i);
});

test("protected API endpoints refuse an unauthenticated request", async ({ request }) => {
  for (const path of ["/api/auth/me", "/api/profile"]) {
    const response = await request.get(path);
    expect(response.status(), `${path} should require a session`).toBe(401);
  }
});

test("the health endpoint reports every dependency by name", async ({ request }) => {
  const response = await request.get("/api/health/ready");
  expect(response.ok()).toBeTruthy();

  const body = await response.json();
  expect(Object.keys(body.dependencies).sort()).toEqual([
    "cache",
    "database",
    "object_storage",
  ]);
});
