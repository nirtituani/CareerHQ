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
# **`HOSTNAME=::` is what makes the container reachable, and the value here has been
# wrong twice.** Next.js standalone binds to `process.env.HOSTNAME`, so this one
# variable decides the socket's address family — and **Railway's private network is
# IPv6**, which is where its healthcheck arrives.
#
# Four frontend deployments failed this way — `75cd8ea`, `73dca63`, `67e9d03`,
# `9edf2f1` — each reporting `failed with service unavailable` on all 14 attempts
# across the 5-minute window. That is a *connection* failure, never a response the
# probe could reject, and it is why CI stayed green throughout: the image builds and
# the container starts, it simply cannot be reached.
#
# **The first fix was `0.0.0.0`, and it did not work.** Docker sets `HOSTNAME` to the
# container id, so the server had been binding one eth0 address; `0.0.0.0` correctly
# widened that to every IPv4 address, and the very next deploy failed identically —
# because `0.0.0.0` is **IPv4-only** and cannot accept an IPv6 connection. Measured
# from another container over Railway's private network:
#
#     IPv6  fd12:2ea:b56c:1:5000:b2:2900:f513   connection refused
#     IPv4  10.128.245.19                       connected
#
# `::` binds the IPv6 wildcard, which on Linux (`bindv6only=0`) serves **both**
# families through IPv4-mapped addresses. Confirmed on a dual-stack Docker network
# with four controlled variants of this image, changing one variable at a time:
#
#     HOSTNAME=0.0.0.0  -> tcp4 00000000:1F90        IPv4 307, IPv6 FAILED
#     HOSTNAME=::       -> tcp6 0000..0000:1F90      IPv4 307, IPv6 307
#
# **`PORT` is deliberately not set here, and that is a measured decision rather than
# an omission.** The same experiment ran both values with `PORT` set and unset: it
# moves which port is listened on and has no effect whatever on the address family or
# on reachability. Hard-coding it would only take away the platform's ability to
# assign one — the rule `entrypoint.sh` already follows on the backend.
ENV NODE_ENV=production \
    HOSTNAME=:: \
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
