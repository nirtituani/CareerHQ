import type { NextConfig } from "next";

/**
 * The browser only ever talks to this origin. Requests to /api/* are proxied to
 * the backend container, which makes every request same-origin: no CORS policy
 * to maintain, and no cross-origin cookie behaviour that works locally and
 * breaks once deployed. See specs/001-platform-foundation/research.md R-003.
 */
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

// This value is resolved now, at build time, and written into
// routes-manifest.json — setting BACKEND_URL later, at runtime, has no effect.
// Falling back silently produces a deployment that serves pages perfectly while
// every /api/* request fails with ECONNREFUSED to a port nothing listens on,
// which reads like a networking fault rather than a missing variable. Saying so
// in the build log is the cheapest way to make that visible.
if (!process.env.BACKEND_URL) {
  console.warn(
    `[next.config] BACKEND_URL is unset; baking in the ${backendUrl} fallback. ` +
      `Correct for a local build. In a container build, pass it as a build ARG — ` +
      `a runtime-only variable arrives too late.`,
  );
}

const nextConfig: NextConfig = {
  // Required by the production Dockerfile stage, which copies .next/standalone.
  output: "standalone",

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },

  /**
   * The backend's SecurityHeadersMiddleware stamps these on /api/* responses,
   * but those are not the responses a browser navigates to — this service
   * serves the HTML, and it was serving it bare. Verifying against the deployed
   * site is what surfaced that; the middleware is correct and always was, and
   * reading it would only ever have confirmed the half of the traffic it sees.
   *
   * Kept deliberately identical to the backend's values, so the two halves of
   * one origin cannot drift into disagreeing about the same policy.
   */
  async headers() {
    const securityHeaders = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "no-referrer" },
    ];

    // Production only, matching the backend. Sending HSTS from plain-HTTP
    // localhost pins a scheme that does not work there, and browsers cache the
    // pin — so the cost of getting this wrong lands on developers, later.
    if (process.env.NODE_ENV === "production") {
      securityHeaders.push({
        key: "Strict-Transport-Security",
        value: "max-age=31536000; includeSubDomains",
      });
    }

    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
