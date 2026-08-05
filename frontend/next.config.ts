import type { NextConfig } from "next";

/**
 * The browser only ever talks to this origin. Requests to /api/* are proxied to
 * the backend container, which makes every request same-origin: no CORS policy
 * to maintain, and no cross-origin cookie behaviour that works locally and
 * breaks once deployed. See specs/001-platform-foundation/research.md R-003.
 */
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

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
