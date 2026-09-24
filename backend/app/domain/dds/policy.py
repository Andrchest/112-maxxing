"""Service status policy — which memo statuses a service may answer (HLD `70-i3-alignment.md`
§70.4.2, §70.6.3; I3 E5a).

The policy is catalog data (`services/<id>.yaml`'s `status_policy`, `app.domain.routing.catalog`),
never scenario data, so the ДДС side reads it from the reference pack the session recorded — not
from the `ScenarioVersion` (INV 3). `NO_REFUSAL` is the 103 policy (`AMBULANCE`): «Не принята» and
«Отказ от выполнения работ» are replaced by `complete_without_brigade` (REQ-5290).
"""

from __future__ import annotations

from app.domain.routing.catalog import ServiceCatalog, StatusPolicy

__all__ = ["DEFAULT", "NO_REFUSAL", "StatusPolicy", "allows_refusal", "policy_of"]

DEFAULT = StatusPolicy.DEFAULT
NO_REFUSAL = StatusPolicy.NO_REFUSAL


def allows_refusal(policy: StatusPolicy) -> bool:
    """`decline` / `refuse` are open to every policy but `NO_REFUSAL`."""
    return policy is not StatusPolicy.NO_REFUSAL


def policy_of(catalog: ServiceCatalog | None, service_id: str) -> StatusPolicy:
    """The service's policy in `catalog`; `DEFAULT` for an id the catalog does not know."""
    entry = None if catalog is None else catalog.get(service_id)
    return StatusPolicy.DEFAULT if entry is None else entry.status_policy
