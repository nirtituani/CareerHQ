FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ---------------------------------------------------------------------------
# Development: hot reload, source mounted over this layer by compose
# ---------------------------------------------------------------------------
FROM node:24-alpine AS dev
WORKDIR /app
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------------------
# Production: standalone build, non-root
# ---------------------------------------------------------------------------
FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# next.config.ts resolves the /api/* proxy destination when the bundle is
# built, not when the server runs — the value ends up in routes-manifest.json.
# Setting BACKEND_URL only at runtime is therefore too late: the build has
# already baked in the localhost fallback, and every /api/* request 500s with
# ECONNREFUSED to a port nothing listens on inside this container.
#
# A Docker build is isolated from the host environment, so a platform can only
# supply a value through a declared ARG. Without this line the variable is
# invisible to the build no matter how it is configured.
ARG BACKEND_URL
ENV BACKEND_URL=${BACKEND_URL}

# Same rule as BACKEND_URL above, and the same trap: `NEXT_PUBLIC_*` is inlined
# into the client bundle when it is built, not read at run time. Setting it only
# in the environment of a running container is too late — the value is already
# baked in, and the logos silently do not load.
ARG NEXT_PUBLIC_LOGO_DEV_TOKEN
ENV NEXT_PUBLIC_LOGO_DEV_TOKEN=${NEXT_PUBLIC_LOGO_DEV_TOKEN}

ENV NEXT_TELEMETRY_DISABLED=1

# The value is echoed inside the RUN rather than before it so that it forms
# part of the layer's cache key. Declaring the ARG alone is not enough: a build
# that changes only the variable produces an identical RUN instruction, so the
# layer is reused and the previously baked destination survives into an image
# that looks freshly built. That failure is silent — the deploy succeeds, the
# health check passes because it probes `/` rather than `/api/*`, and only a
# real API request reveals the stale value.
RUN echo "Building with BACKEND_URL=${BACKEND_URL:-<unset — will bake in the localhost fallback>}" \
    && npm run build

FROM node:24-alpine AS runner
WORKDIR /app
# **`HOSTNAME=0.0.0.0` is what makes the container reachable, and its absence broke
# three consecutive deployments.** Next.js standalone binds to `process.env.HOSTNAME`,
# and Docker sets that to the container id — which resolves to the single eth0
# address. Measured inside the running container: the listener was bound to
# `10.128.245.19:8080`, and `127.0.0.1:8080` and `localhost:8080` both answered
# **connection refused**, while the container IP answered `307`.
#
# Railway's healthcheck then reported `failed with service unavailable` on all 14
# attempts across its 5-minute window — a *connection* failure, never a response it
# could reject. The mis-binding was always there and only became fatal when the probe
# started arriving on loopback; the repository never changed, which is why three
# deploys failed with an identical image recipe and an identical startup line.
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
# 8080, not 3000: the platform injects `PORT=8080` and the server honours it, so the
# declared port has to say the same thing the process actually does. No `PORT` is set
# here — the application already listens on what it is given, and hard-coding one
# would take that away. This is the frontend's version of the rule the backend
# entrypoint already follows.
EXPOSE 8080
CMD ["node", "server.js"]
