"""Our own software SIP/RTP gateway (HLD 80 §80.2, D22, epic I3 E6a).

A registrar with Digest, a UAS for INVITE/ACK/BYE/CANCEL/OPTIONS, RTP G.711 A/μ-law through the
stdlib `audioop`, and a `RoomPort` bridge that makes a SIP call one more participant of a LiveKit
room. It lives under `voice_agent.transport` because `LiveKitRoomBridge` imports the `livekit` rtc
SDK, and this package is the only place allowed to (D2/D9, `backend/tools/check_imports.py`); every
other module here is stdlib-only and imports nothing heavy at module scope.

`SipCallTransport` (`transport/sip_transport.py`) is a different thing and stays a stub: it is plan
B (direct RTP into the agent, no SFU hop), built only if the E6a falsification checkpoint fires
(80 §80.11).
"""
