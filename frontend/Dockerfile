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

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
