"""Lessons (занятия): a stream of cards as N ordinary sessions (HLD `70-i3-alignment.md` §70.3,
D15; I3 E4a).

`plan` holds the scheduling vocabulary (`ArrivalKind`, `Arrival`, `PlanEntry`,
`LessonParticipant`) and the pure arrival evaluation; `lesson` holds the aggregate and
`LESSON_TRANSITIONS`; `weights` (I3 E9a, §70.3.7) the card metadata a weight proposer may read,
the deterministic heuristic and the proposal set an instructor accepts. A lesson is scheduling,
not simulation: it has no event log of its own.
"""
