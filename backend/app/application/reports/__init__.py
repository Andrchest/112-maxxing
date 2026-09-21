"""The post-session report and replay (epic E16; SPEC §29, §27, §2; HLD D11, D12, D3, D6, D9).

The package is one use case per operation plus one **pure** module per SPEC §29 section, so that
"what the report shows" is testable without a database and "who may see it" is testable without a
report:

| module | owns |
|:--|:--|
| `visibility` | who sees which section (R3) — pure, table-tested, the only place the rule lives |
| `timeline` | §29 item 4 plus the Russian `summary_ru` per `EventType` |
| `transcript` | §29 items 5-7, including the `TRAINEE -> OPERATOR` speaker rename (R5) |
| `truth_vs_card` | §29 item 9 — the one place `WorldTruth` reaches a human (D11) |
| `dds_decisions` | §29 item 11 — the legs verbatim |
| `resource_timeline` | §29 item 12 |
| `timing_metrics` | §29 item 13 and SPEC §27's aggregate, shared with `listInferenceMetrics` |
| `assemble_report` | `getSessionReport` — reads stored scores, never recomputes them (R1) |
| `release_report` | `releaseReportToTrainee` — a visibility flag, emitting no event (R2) |
| `serve_audio_segment` | `getAudioSegment` with real HTTP Range (R7) |
| `list_inference_metrics` | `listInferenceMetrics` |

The LLM explanation is deliberately **not** here as a peer of `assemble_report`: it is generated
from an already persisted `ScoreReport`, stored separately, and holds no write path to the score
tables (SPEC §2, D11). Its use case lives beside these and is constructed with a read-only score
reader.
"""

from __future__ import annotations

from app.application.reports.assemble_report import GetSessionReport, SessionReportView
from app.application.reports.list_inference_metrics import (
    InferenceMetricsPage,
    ListInferenceMetrics,
)
from app.application.reports.release_report import ReleaseReportToTrainee
from app.application.reports.serve_audio_segment import (
    AudioPurgedError,
    AudioSegmentNotFoundError,
    AudioSegmentResponse,
    RangeNotSatisfiableError,
    ServeAudioSegment,
)
from app.application.reports.visibility import (
    ReportNotReleasedError,
    ReportVisibility,
    report_visibility,
)

__all__ = [
    "AudioPurgedError",
    "AudioSegmentNotFoundError",
    "AudioSegmentResponse",
    "GetSessionReport",
    "InferenceMetricsPage",
    "ListInferenceMetrics",
    "RangeNotSatisfiableError",
    "ReleaseReportToTrainee",
    "ReportNotReleasedError",
    "ReportVisibility",
    "ServeAudioSegment",
    "SessionReportView",
    "report_visibility",
]
