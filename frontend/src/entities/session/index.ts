// Entity: training session. Session lifecycle, role stages and the event-sourced audit log
// (SPEC §7, §8) land here starting E5/E7. Three Zustand stores, one per realtime concern (D12):
// who is signed in, the session's event log, and the phone widget's call state.
export * from './auth-store';
export * from './session-events-store';
export * from './call-state-store';
