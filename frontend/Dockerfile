# syntax=docker/dockerfile:1
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# Serve the static bundle with a tiny, configurable static server that also
# proxies /api to the backend container.
FROM node:20-alpine AS runtime

WORKDIR /app

COPY --from=build /app/dist ./dist
COPY server.mjs ./server.mjs

ENV PORT=5173 \
    API_PROXY=http://backend:8000

EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -qO- http://localhost:5173/ >/dev/null || exit 1

CMD ["node", "server.mjs"]
