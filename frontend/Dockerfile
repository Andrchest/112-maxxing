# Frontend dev-server image (SPEC §36, D1). Build context is `frontend/` itself (a plain npm
# project, not a member of the Python `sim112-workspace`).
#
# Runs the Vite DEV server, not a production build: this compose stack is the local demo/dev stack
# `infra/docker-compose.yml` describes (SPEC §36 "Use Docker Compose for the current product/demo"),
# and the existing dev port (5173, already referenced by `.env.example`'s
# `SIM_CORS_ALLOW_ORIGINS`) is what the rest of the stack (backend CORS, the owner's browser) already
# expects. A production `vite build` + static server is out of this task's scope.
FROM node:22-slim AS base

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `VITE_API_PROXY_TARGET` (see `vite.config.ts`) must point at the compose-internal backend
# hostname, not `127.0.0.1` — `infra/docker-compose.yml` sets it to `http://backend:8100`.
ENV VITE_API_PROXY_TARGET=http://backend:8100

EXPOSE 5173

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD wget -q -O - "http://127.0.0.1:5173/" >/dev/null 2>&1 || exit 1

# `--host 0.0.0.0`: the Vite dev server binds loopback-only by default, which is unreachable from
# outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
