"""The four information layers (HLD `10-domain-model.md` §10.3, D3, SPEC §3): `WorldTruth`,
`CallerBelief`, `OperatorCard` and `HandoffSnapshot`. No type here inherits from, embeds, or holds
a reference to another layer's type, and the four layer modules (`world_truth`, `caller_belief`,
`operator_card`, `handoff`) are pairwise import-free.
"""
