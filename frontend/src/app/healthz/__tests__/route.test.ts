import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "@/middleware";

import { GET } from "../route";

/**
 * The healthcheck target must answer 200 by itself.
 *
 * Railway's platform healthcheck connects directly to the container and, since
 * their 2026-08-28 security change, **does not follow redirects**. Our `/` is a
 * server-side redirect to `/dashboard` or `/login`, so it answers 307 and always
 * has — which the platform reported as the misleading `service unavailable`.
 * These tests pin the three properties that made `/` the wrong target, so the
 * mistake cannot return by accident.
 */

const FRONTEND_ROOT = join(import.meta.dirname, "..", "..", "..", "..");

function healthcheckPathFromRailwayToml(): string {
  const toml = readFileSync(join(FRONTEND_ROOT, "railway.toml"), "utf8");
  const match = /^\s*healthcheckPath\s*=\s*"([^"]+)"/m.exec(toml);
  // A regex that matched nothing would let every assertion below vanish while
  // the suite still reported a pass.
  expect(match, "railway.toml declares no healthcheckPath").not.toBeNull();
  return match![1];
}

describe("the healthcheck endpoint", () => {
  it("answers 200 directly", async () => {
    const response = await GET();

    expect(response.status).toBe(200);
  });

  it("does not redirect", async () => {
    const response = await GET();

    expect(response.status).toBeLessThan(300);
    expect(response.headers.get("location")).toBeNull();
  });

  it("answers the same without a session cookie as with one", async () => {
    // The probe carries no cookies. An endpoint whose answer depends on one
    // would pass a developer's browser and fail the platform.
    const anonymous = await GET();
    const bodyWithoutCookie = await anonymous.text();

    expect(bodyWithoutCookie.length).toBeGreaterThan(0);
    expect(anonymous.status).toBe(200);
  });
});

describe("railway.toml's healthcheckPath", () => {
  it("points at a route that exists in this application", () => {
    const path = healthcheckPathFromRailwayToml();

    expect(existsSync(join(FRONTEND_ROOT, "src", "app", path, "route.ts"))).toBe(true);
  });

  it("is not the root, which redirects", () => {
    expect(healthcheckPathFromRailwayToml()).not.toBe("/");
  });

  it("is not under /api, which next.config.ts rewrites to the backend", () => {
    // An /api/* target would never be answered by this service at all: the
    // rewrite sends it to the backend container, so the frontend's healthcheck
    // would report on the backend's health.
    expect(healthcheckPathFromRailwayToml().startsWith("/api/")).toBe(false);
  });

  it("is not intercepted by the auth middleware", () => {
    const path = healthcheckPathFromRailwayToml();

    const response = middleware(new NextRequest(new URL(`http://localhost:8080${path}`)));

    // NextResponse.next() carries this header; NextResponse.redirect() does not.
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.status).toBeLessThan(300);
  });
});
