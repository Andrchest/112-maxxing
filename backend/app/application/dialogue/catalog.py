"""The fact catalog the interpreter LLM sees (HLD `10-domain-model.md` §10.4, D10, SPEC §20).

`FactCatalogEntry` is the only fact structure that ever reaches the interpreter prompt:
`fact_id`, `label_ru`, `aliases_ru`, `categories` — and nothing else. Not a value, world or
caller; not a `KnowledgeState`; not a `DisclosurePolicy`. The entry type simply has no field to
put any of them in, which is what makes "the interpreter never sees fact values" a property of the
types rather than a promise about the prompt builder.

A `NEVER_DISCLOSE` fact stays **in** the catalog. The interpreter's job is to recognise that the
operator asked about the fire source; refusing to answer is the gate's job, and it can only refuse
a request it was told about (§10.12 row 2). Dropping such facts here would instead make the
operator's question unintelligible and lose the `FACT_GATE_EVALUATED` evidence that the question
was asked at all.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.facts.definitions import FactCatalog, FactDefinition

__all__ = ["build_fact_catalog"]


def build_fact_catalog(definitions: Mapping[str, FactDefinition]) -> FactCatalog:
    """Project the joined fact definitions onto the value-free catalog, in scenario order."""
    return FactCatalog.from_definitions(definitions)
