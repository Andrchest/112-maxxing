"""Shared value aliases (HLD `10-domain-model.md` §10.3).

`FactValue` is defined exactly once here; every later domain (and application) module imports it
from this module rather than redefining it.
"""

from __future__ import annotations

FactValue = str | int | float | bool | list[str] | None
