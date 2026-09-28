// I6 HTTP: features that need a secure context (LiveKit media joins, so the phone widgets and
// their call buttons) switch off at RUNTIME when the page itself is not one — no build flag, no
// code deletion, so the https demo keeps every feature. `window.isSecureContext` is false on a
// plain http origin, even inside the tailnet (the tailnet hostname is not `localhost`), and true
// on https and on `localhost`. A single wrapper so every call site — and every test, which stubs
// `window.isSecureContext` — shares one source of truth instead of reading the global directly.
export function isSecureContext(): boolean {
  return window.isSecureContext === true;
}
