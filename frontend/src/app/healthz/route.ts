/**
 * The platform healthcheck target (`frontend/railway.toml`).
 *
 * This exists because `/` cannot serve the purpose. `/` is a server-side
 * redirect to `/dashboard` or `/login` depending on a session cookie, so it
 * answers **307**, and always has. Railway's healthcheck stopped following
 * redirects in their 2026-08-28 security change and reported the resulting
 * non-2xx as `service unavailable`, which reads as a connection fault and is
 * not one. Nine consecutive deployments failed on it.
 *
 * The three properties that matter here are the three `/` lacks:
 *
 * - **200 directly.** No redirect, so nothing depends on the prober following
 *   one.
 * - **No session, no cookies, no request context.** The probe carries none. An
 *   endpoint that read a cookie would pass in a browser and fail the platform.
 * - **No dependencies.** Liveness is the right check for this service — it
 *   holds no dependency of its own, and the backend's own readiness check gates
 *   the part that does. Reaching the backend from here would make one failing
 *   service look like two.
 *
 * It is not under `/api/*`: `next.config.ts` rewrites that prefix to the
 * backend container, so an `/api/health` here would never be answered by this
 * service at all.
 */

// Answered by the running server on every request rather than prerendered at
// build time. A constant that a cache could satisfy would keep reporting 200
// for a process that had stopped, which is the one thing this endpoint exists
// to notice.
export const dynamic = "force-dynamic";

export function GET(): Response {
  return new Response("ok", {
    status: 200,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
