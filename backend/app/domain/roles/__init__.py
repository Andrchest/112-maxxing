"""The `RoleModule` abstraction: `Permission`, `ActionDescriptor`, `RoleModule` (`module.py`),
`ROLE_MODULES` (`registry.py`), `DataVisibilityPolicy` (`visibility.py`), and the
`Operator112Module`, `DDSModule`, `EDDSModule` implementations (HLD `10-domain-model.md` §10.9,
SPEC §14, D6).

`app.domain.roles` re-exports `ROLE_MODULES` (ruling R5 of this task's brief) so callers may write
either `from app.domain.roles import ROLE_MODULES` or `from app.domain.roles.registry import
ROLE_MODULES`.
"""

from __future__ import annotations

from app.domain.roles.registry import ROLE_MODULES

__all__ = ["ROLE_MODULES"]
