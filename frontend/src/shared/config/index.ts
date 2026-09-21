// Runtime configuration. The dev server proxies /api -> VITE_API_PROXY_TARGET (see
// vite.config.ts, default http://127.0.0.1:8100); in production the same relative path is
// served by the reverse proxy in front of the FastAPI backend (SPEC §32, §36).
export const API_BASE_PATH = '/api/v1';

/** WebSocket realtime channel base path (D8, `docs/hld/40-realtime-protocol.md` §40.1). Same
 * origin as the REST API; the dev proxy forwards the upgrade too (`ws: true`). */
export const WS_BASE_PATH = '/api/v1/ws';

/** sessionStorage keys for the in-memory-plus-tab-persisted auth token (D12 design decision
 * #4; SPEC §39 — a refresh must not silently drop the session). */
export const AUTH_TOKEN_STORAGE_KEY = 'auth.token';
export const AUTH_USER_STORAGE_KEY = 'auth.user';
