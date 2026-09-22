"""E20-I proof: one real call through `make up` with the shipped DEV_3060TI (Qwen3-TTS primary).

Instructor creates + starts a session over the REST API, the trainee answers, the mic-less
injection CLI plays three trainee turns, then the instructor-side event log is read back and the
caller-side evidence (CALLER_RESPONSE_GENERATED / CALLER_TTS_STARTED{voice_id_native} /
CALLER_TTS_ENDED / FACTS_DELIVERED, and any MODEL_ERROR / MODEL_FALLBACK_USED) is saved.

Usage: uv run python /tmp/teamwork-112-maxxing/logs/e20i/proof.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from app.config.settings import read_env_value

API = "http://127.0.0.1:8100/api/v1"
OUT = Path("/home/andreipc/112-maxxing/docs/benchmarks/results/dod-walk-20260922/e20i")
TURNS_SRC = Path("/home/andreipc/112-maxxing/benchmarks/data/e2e/turns.jsonl")
TURN_IDS = ("greeting", "address", "what_is_burning")
CALLER_EVENTS = {
    "CALL_RINGING",
    "CALL_CONNECTED",
    "ASR_FINAL",
    "CALLER_RESPONSE_GENERATED",
    "CALLER_TTS_STARTED",
    "CALLER_TTS_ENDED",
    "FACTS_DELIVERED",
    "CALLER_UTTERANCE_INTERRUPTED",
    "MODEL_ERROR",
    "MODEL_FALLBACK_USED",
    "INFERENCE_HEALTH_CHANGED",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def login(c: httpx.Client, user: str, env: str) -> dict:
    r = c.post(f"{API}/auth/login", json={"username": user, "password": read_env_value(env)})
    r.raise_for_status()
    return r.json()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    c = httpx.Client(timeout=120)
    inst = login(c, "instructor", "SIM_SEED_INSTRUCTOR_PASSWORD")
    tr = login(c, "trainee", "SIM_SEED_TRAINEE_PASSWORD")
    ih = {"Authorization": f"Bearer {inst['access_token']}"}
    th = {"Authorization": f"Bearer {tr['access_token']}"}

    sc = c.get(f"{API}/scenarios", headers=ih).json()["items"][0]
    version_id = c.get(f"{API}/scenarios/{sc['scenario_id']}/versions", headers=ih).json()[
        "items"
    ][0]["id"]
    body = {
        "scenario_version_id": version_id,
        "session_mode": "FULL_CYCLE_SINGLE_TRAINEE",
        "participants": [{"user_id": tr["user"]["id"], "assigned_role_type": "OPERATOR_112"}],
    }
    r = c.post(f"{API}/sessions", headers=ih, json=body)
    log(f"createSession -> {r.status_code}")
    r.raise_for_status()
    sid = r.json().get("session_id") or r.json()["id"]
    r = c.post(f"{API}/sessions/{sid}/start", headers=ih)
    log(f"startSession -> {r.status_code} {r.text[:300] if r.status_code >= 400 else ''}")
    if r.status_code >= 400:
        (OUT / "start-refused.txt").write_text(r.text)
        return 1

    deadline = time.time() + 120
    ringing = None
    while time.time() < deadline and ringing is None:
        items = c.get(
            f"{API}/sessions/{sid}/events", headers=ih, params={"after_seq_no": 0, "limit": 1000}
        ).json()["items"]
        ringing = next((e for e in items if e["event_type"] == "CALL_RINGING"), None)
        time.sleep(1)
    if ringing is None:
        log("no CALL_RINGING within 120 s")
        return 2
    log(f"CALL_RINGING seq {ringing['seq_no']} offset {ringing.get('monotonic_offset_ms')} ms")
    r = c.post(f"{API}/sessions/{sid}/operator/call/answer", headers=th)
    log(f"answerCall -> {r.status_code}")

    turns = OUT / "turns.jsonl"
    rows = [json.loads(line) for line in TURNS_SRC.read_text().splitlines() if line.strip()]
    with turns.open("w") as fh:
        for row in rows:
            if row["id"] in TURN_IDS:
                row["path"] = str((TURNS_SRC.parent / row["path"]).resolve())
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    log("inject: 3 trainee turns, --wait-caller")
    inject = subprocess.run(
        [
            "uv", "run", "python", "-m", "voice_agent.tools.inject",
            "--session", sid, "--turns", str(turns), "--wait-caller",
        ],
        cwd="/home/andreipc/112-maxxing",
        capture_output=True,
        text=True,
        timeout=600,
    )
    (OUT / "inject.log").write_text(inject.stdout + "\n--- stderr ---\n" + inject.stderr)
    log(f"inject exit {inject.returncode}")
    time.sleep(10)

    items = c.get(
        f"{API}/sessions/{sid}/events", headers=ih, params={"after_seq_no": 0, "limit": 1000}
    ).json()["items"]
    (OUT / "events-instructor-full.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    caller = [
        {
            "seq_no": e["seq_no"],
            "offset_ms": e.get("monotonic_offset_ms"),
            "event_type": e["event_type"],
            "payload": e["payload"],
        }
        for e in items
        if e["event_type"] in CALLER_EVENTS
    ]
    (OUT / "events-caller-excerpt.json").write_text(json.dumps(caller, ensure_ascii=False, indent=1))
    for e in caller:
        p = e["payload"]
        brief = {
            k: p[k]
            for k in (
                "text", "planned_text", "voice_id_native", "provider", "component", "stage",
                "error_code", "fact_ids", "speech_end_to_first_audio_ms", "new_status", "service",
            )
            if k in p
        }
        log(f"  seq {e['seq_no']:>4} +{e['offset_ms']:>7} ms {e['event_type']:<26} {json.dumps(brief, ensure_ascii=False)[:220]}")
    counts: dict[str, int] = {}
    for e in caller:
        counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
    (OUT / "summary.json").write_text(json.dumps({"session_id": sid, "counts": counts}, indent=1))
    log(f"session {sid} counts {counts}")
    ok = counts.get("CALLER_TTS_STARTED", 0) >= 1 and counts.get("FACTS_DELIVERED", 0) >= 1
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
