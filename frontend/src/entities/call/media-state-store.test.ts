import { afterEach, describe, expect, it } from 'vitest';
import { useMediaStateStore } from './media-state-store';

describe('useMediaStateStore', () => {
  afterEach(() => {
    useMediaStateStore.getState().reset();
  });

  it('starts idle, unmuted, level 0, no mic permission problem', () => {
    const state = useMediaStateStore.getState();
    expect(state.phase).toBe('idle');
    expect(state.muted).toBe(false);
    expect(state.level).toBe(0);
    expect(state.micPermissionDenied).toBe(false);
  });

  it('setPhase/setMuted/setLevel/setMicPermissionDenied update independently', () => {
    useMediaStateStore.getState().setPhase('connecting');
    useMediaStateStore.getState().setMuted(true);
    useMediaStateStore.getState().setLevel(0.5);
    useMediaStateStore.getState().setMicPermissionDenied(true);

    const state = useMediaStateStore.getState();
    expect(state.phase).toBe('connecting');
    expect(state.muted).toBe(true);
    expect(state.level).toBe(0.5);
    expect(state.micPermissionDenied).toBe(true);
  });

  it('reset returns every field to its initial value', () => {
    useMediaStateStore.getState().setPhase('connected');
    useMediaStateStore.getState().setMuted(true);
    useMediaStateStore.getState().setLevel(0.9);
    useMediaStateStore.getState().setMicPermissionDenied(true);

    useMediaStateStore.getState().reset();

    const state = useMediaStateStore.getState();
    expect(state.phase).toBe('idle');
    expect(state.muted).toBe(false);
    expect(state.level).toBe(0);
    expect(state.micPermissionDenied).toBe(false);
  });
});
