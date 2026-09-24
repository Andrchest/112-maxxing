// Entity: the phone widget's call state selectors (SPEC §32/§34; D12). The raw store lives in
// `entities/session/call-state-store.ts` (E8-A, one Zustand store per realtime concern per D12);
// this module holds only the pure logic layered on top of it — folding a realtime event onto a
// `CallStateView` and formatting the call timer — kept separate so it can be unit-tested without
// a store.
export * from './apply-call-event';
export * from './format';
export * from './media-state-store';
// I3 E6b: the ДДС phone line, one entry per `call_id` (HLD 80 §80.3).
export * from './dds-call-store';
