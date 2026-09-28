import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// I6 HTTP: components read `window.isSecureContext` at runtime (shared/lib/secure-context.ts) to
// switch off features that need one (the phone, the microphone). jsdom never sets the property
// (always `undefined`) — default it to `true` so the existing suite keeps testing the ordinary
// https behaviour; a test for the insecure branch stubs it with
// `vi.stubGlobal('isSecureContext', false)`, restored by that file's own `vi.unstubAllGlobals()`.
Object.defineProperty(window, 'isSecureContext', { value: true, writable: true, configurable: true });

afterEach(() => {
  cleanup();
});
