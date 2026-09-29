"""Audit adapters beside the `audit_log` repository (I7 E43): the request-scoped change list."""

from __future__ import annotations

from app.infrastructure.audit.context_change_collector import ContextVarAuditChanges

__all__ = ["ContextVarAuditChanges"]
