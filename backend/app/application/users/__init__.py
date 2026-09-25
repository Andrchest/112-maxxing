"""Accounts backend — `createUser`, `updateUser`, `resetUserPassword` (I4 E28, §71.5).

ТЗ ¶195-¶197: an ADMIN can create an account of any role, change its role/display name/active
flag, and reset its password. `listUsers`'s own `include_inactive` addition stays with the read
side (`app.application.auth.list_users`) — this package is only the writes.

Every action is audited by E25's `AuditMiddleware` automatically (it reads the ASGI scope; no
call here writes an `audit_log` row itself). What this package *does* enforce is the two
technical guards `71-i4-wave4.md` §71.5 names: an ADMIN cannot block or demote its own account
(`SelfModificationForbiddenError`), and the last active ADMIN cannot be blocked or demoted
(`LastAdminRequiredError`) — see `update_user.py` and `set_active.py`.
"""

from __future__ import annotations
