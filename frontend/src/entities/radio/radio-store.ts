// Entity: the DDS radio log (`docs/hld/10-domain-model.md` §10.7 `RadioMessage`; D5, D12). There
// is no radio table (`20-db-schema.md` §20.1) — `listRadioMessages` projects it from
// `RADIO_MESSAGE_CREATED` events, filtered `to_role == caller's role`. Fed ONLY by server data:
// `listRadioMessages` and the `RADIO_MESSAGE_CREATED` WS event fold in `apply-radio-event.ts`.
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type RadioMessageView = components['schemas']['RadioMessageView'];

interface RadioStoreState {
  messages: RadioMessageView[];
  lastSeqNo: number;
  /** Replaces the log wholesale with the server's latest `listRadioMessages` page, in log order. */
  setMessages: (messages: RadioMessageView[], lastSeqNo: number) => void;
  reset: () => void;
}

export const useRadioStore = create<RadioStoreState>((set) => ({
  messages: [],
  lastSeqNo: 0,
  setMessages: (messages, lastSeqNo) => set({ messages, lastSeqNo }),
  reset: () => set({ messages: [], lastSeqNo: 0 }),
}));
