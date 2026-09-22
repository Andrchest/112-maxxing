"""Fixtures for the retention-purge integration tests (E18-D, R8, real PostgreSQL and real files).

`PurgeRecordings` reads exactly the rows and the retention reference a real 112 -> DDS -> close
flow produces (`simulation_sessions.completed_at`, `audio_segments`), so this package reuses the
report tests' `completed` fixture chain wholesale rather than re-seeding a scored, completed
session by hand. Re-exported by module-attribute assignment, not `import`, because a conftest
already loaded elsewhere (`tests.api.reports.conftest` is loaded by that package's own tests)
cannot be registered a second time — the same pattern `test_inv_13_refresh_restores_state.py` and
`test_inv_14_asr_failure_keeps_session.py` use.
"""

from __future__ import annotations

from tests.api.reports import conftest as _reports_fixtures

OperatorFlow = _reports_fixtures.OperatorFlow
RecordedSegment = _reports_fixtures.RecordedSegment

client = _reports_fixtures.client
clean_database = _reports_fixtures.clean_database
tokens = _reports_fixtures.tokens
users = _reports_fixtures.users
hasher = _reports_fixtures.hasher
inference = _reports_fixtures.inference
publisher = _reports_fixtures.publisher
redis_client = _reports_fixtures.redis_client
demo_version_id = _reports_fixtures.demo_version_id
unit_of_work = _reports_fixtures.unit_of_work
auth = _reports_fixtures.auth
flow = _reports_fixtures.flow
ringing = _reports_fixtures.ringing
connected = _reports_fixtures.connected
interview = _reports_fixtures.interview
uow_factory = _reports_fixtures.uow_factory
clock = _reports_fixtures.clock
container = _reports_fixtures.container
idempotency = _reports_fixtures.idempotency
prepared = _reports_fixtures.prepared
handed_off = _reports_fixtures.handed_off
in_transition = _reports_fixtures.in_transition
dds_active = _reports_fixtures.dds_active
dds_post = _reports_fixtures.dds_post
dds_get = _reports_fixtures.dds_get
acknowledge = _reports_fixtures.acknowledge
open_selection = _reports_fixtures.open_selection
select = _reports_fixtures.select
dispatch = _reports_fixtures.dispatch
at = _reports_fixtures.at
events_of = _reports_fixtures.events_of
event_types = _reports_fixtures.event_types
api_settings = _reports_fixtures.api_settings
#: `api_settings`'s own dependency (a private fixture in `tests.api.reports.conftest`); needed
#: here too because pytest resolves a fixture's dependencies by name in the *requesting* module's
#: closure, not the module the fixture function was originally defined in.
_api_settings_base = _reports_fixtures._api_settings_base
resolved = _reports_fixtures.resolved
completed = _reports_fixtures.completed
recorded_segment = _reports_fixtures.recorded_segment
report = _reports_fixtures.report
release = _reports_fixtures.release
