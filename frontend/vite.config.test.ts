// I4 E27 (docs/hld/71-i4-wave4.md §71.4): behind the TLS edge the browser's Host header reaches the
// Vite dev server, so a classroom server's hostname must be in `server.allowedHosts`
// (VITE_ALLOWED_HOSTS). Unset, Vite keeps its own default (localhost and any IP address).
import type { ConfigEnv, UserConfig } from 'vite';
import { afterEach, describe, expect, it, vi } from 'vitest';
import viteConfig from './vite.config';

const ENV: ConfigEnv = { command: 'serve', mode: 'test' };

function resolveConfig(): UserConfig {
  if (typeof viteConfig !== 'function') throw new Error('vite.config.ts must export a config function');
  return viteConfig(ENV) as UserConfig;
}

describe('vite.config server.allowedHosts (I4 E27)', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('lists every VITE_ALLOWED_HOSTS entry, trimmed, empty entries dropped', () => {
    vi.stubEnv('VITE_ALLOWED_HOSTS', ' sim112-server, .classroom.lan ,, ');
    expect(resolveConfig().server?.allowedHosts).toEqual(['sim112-server', '.classroom.lan']);
  });

  it('leaves Vite’s default in place when VITE_ALLOWED_HOSTS is empty', () => {
    vi.stubEnv('VITE_ALLOWED_HOSTS', '');
    const server = resolveConfig().server;
    expect(server && 'allowedHosts' in server).toBe(false);
    // The /api proxy (with the realtime WebSocket upgrade) is untouched.
    expect(server?.proxy?.['/api']).toMatchObject({ ws: true, changeOrigin: true });
  });
});
