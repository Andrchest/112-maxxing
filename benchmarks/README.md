# benchmarks

Distribution `sim-benchmarks` (workspace member; no installable package code yet).

The five benchmark scripts (`benchmark_asr.py`, `benchmark_llm.py`, `benchmark_tts.py`,
`benchmark_e2e.py`, `benchmark_vram.py` — SPEC §35, §40) arrive in **E19** ("Benchmarks and real
models"), together with `benchmarks/data/` and JSON/CSV export. Until then this directory only
holds workspace plumbing (`pyproject.toml`) so `uv sync --all-packages` resolves the full
workspace.
