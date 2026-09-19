// Runtime configuration. The dev server proxies /api -> http://localhost:8000
// (see vite.config.ts); in production the same relative path is served by
// the reverse proxy in front of the FastAPI backend (SPEC §32, §36).
export const API_BASE_PATH = '/api/v1';
