"""SPEC §39 resilience suite — one module per numbered behaviour (E18-D, R11).

`test_39_1_browser_refresh.py` .. `test_39_6_gpu_oom.py`: each module proves exactly one of the
six SPEC §39 requirements and, in every test, the cross-cutting closing rule that applies to all
six alike — "Never silently reset the simulation" — rather than that rule getting a test of its
own (see `conftest.py`'s `assert_prefix_preserved`).

Modules 1-4 (browser refresh, TTS failure, invalid LLM structured output, ASR failure) are E18-D's;
modules 5-6 (LiveKit temporary reconnect, GPU OOM) are E18-C's, added alongside this package.
"""
