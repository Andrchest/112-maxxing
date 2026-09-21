"""The voice turn path (HLD `50-voice-pipeline.md` §3, §4, §6, §9; D9; SPEC §15–§18).

Everything here is transport-agnostic and model-agnostic: it consumes the `CallTransport`,
`VADProvider`, `Clock` and `UnitOfWork` ports and nothing else, which is what lets the whole turn
loop be exercised against `FakeCallTransport` + `EnergyVAD` + `FakeClock` with no LiveKit, no GPU
and no model weights (D13).

E11 ships the plumbing only: transport, resampling, turn detection, chunked playback with cancel,
recording and the event append. ASR, the interpreter, the Fact Access Gate, the generator, the
validator and TTS are typed seams here and real code in E12–E14; `NullTurnResponder` is what fills
the seam until then.
"""
