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
};

export default nextConfig;
