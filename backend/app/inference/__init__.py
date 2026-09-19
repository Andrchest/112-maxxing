"""Inference layer.

Implements application-layer ports against ML/inference providers (ASR, LLM, TTS, VAD):
`inference -> application, domain` (D2). Heavy ML dependencies are optional extras imported lazily
inside adapters, never at module import time (D1). Depends on `app.application` and `app.domain`;
never depended on by them.
"""
