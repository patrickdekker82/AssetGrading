# Web interface: Next.js standalone output. Always build on the Mac, never on the NAS:
#   docker buildx build --platform linux/amd64 ...
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 graadmeter && adduser -S -u 10001 -G graadmeter graadmeter
COPY --from=build --chown=graadmeter:graadmeter /app/.next/standalone ./
COPY --from=build --chown=graadmeter:graadmeter /app/.next/static ./.next/static
COPY --from=build --chown=graadmeter:graadmeter /app/public ./public
USER graadmeter
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/crypto || exit 1
CMD ["node", "server.js"]
