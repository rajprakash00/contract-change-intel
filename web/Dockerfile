# Build stage: install locked deps, run next build with the Auth0 SPA values
# inlined (NEXT_PUBLIC_* is compiled into the client bundle at build time —
# they are public identifiers, not secrets). Non-Auth0 build args fall back to
# harmless placeholders; providers.tsx renders its "not configured" notice.
FROM node:24-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_AUTH0_DOMAIN=""
ARG NEXT_PUBLIC_AUTH0_CLIENT_ID=""
ARG NEXT_PUBLIC_AUTH0_AUDIENCE=""
ENV NEXT_PUBLIC_AUTH0_DOMAIN=$NEXT_PUBLIC_AUTH0_DOMAIN \
    NEXT_PUBLIC_AUTH0_CLIENT_ID=$NEXT_PUBLIC_AUTH0_CLIENT_ID \
    NEXT_PUBLIC_AUTH0_AUDIENCE=$NEXT_PUBLIC_AUTH0_AUDIENCE \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Runtime: standalone server only, non-root.
FROM node:24-slim
WORKDIR /app
RUN groupadd --system --gid 1001 nodejs && useradd --system --uid 1001 --gid nodejs nextjs
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
CMD ["node", "server.js"]
