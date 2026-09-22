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

# This base image has neither `wget` nor `curl` (verified 2026-09-22, E20-G: `which wget curl node`
# inside the built image prints only `/usr/local/bin/node`; the previous `wget` probe exited 127, so
# the container was permanently `unhealthy` and `docker compose up --wait` could never succeed).
# Node 22's global `fetch` is the one runtime the image is guaranteed to have. Kept in step with the
# `frontend.healthcheck` in `infra/docker-compose.yml`, which overrides this one under compose.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:5173/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# `--host 0.0.0.0`: the Vite dev server binds loopback-only by default, which is unreachable from
# outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
