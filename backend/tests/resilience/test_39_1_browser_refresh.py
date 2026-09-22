"""SPEC §39 #1 — "Browser refresh: restore active session." (`docs/SPEC.md:1029-1030`).

The mechanism (HLD `40-realtime-protocol.md` §40.5, D8): `GET /sessions/{id}/snapshot` gives a
refreshed page everything it needs to render immediately, and a WebSocket `{"type":"resume",
"after_seq_no":N}` replays anything committed since. `test_inv_13_refresh_restores_state.py`
already proves the deep client-fold equivalence between a refreshed client and one that never
refreshed, across three refresh points and a full backend restart — this module does not repeat
that; it drives the same public seam (REST snapshot + WS resume) end-to-end for the one thing
SPEC §39 itself asserts, and closes on the cross-cutting "never silently reset" check every §39
module carries: session state, incident id and the event log's prefix all survive a refresh
untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.domain.events.types import EventType

from tests.api.conftest import api_settings as api_settings
from tests.api.conftest import auth
from tests.api.conftest import clean_database as clean_database
from tests.api.conftest import client as client
from tests.api.conftest import demo_version_id as demo_version_id
from tests.api.conftest import hasher as hasher
from tests.api.conftest import inference as inference
from tests.api.conftest import redis_client as redis_client
from tests.api.conftest import tokens as tokens
from tests.api.conftest import unit_of_work as unit_of_work
from tests.api.conftest import users as users
from tests.api.operator.conftest import OperatorFlow
from tests.api.operator.conftest import container as container
from tests.api.operator.conftest import flow as flow
from tests.api.operator.conftest import idempotency as idempotency
from tests.api.realtime.conftest import ASGIWebSocket
from tests.api.realtime.conftest import publisher as publisher
from tests.api.realtime.conftest import websocket as websocket
from tests.resilience.conftest import assert_prefix_preserved

pytestmark = pytest.mark.integration

DELIVERY_TIMEOUT_S = 10.0
QUIET_S = 0.2


async def _events(client: httpx.AsyncClient, session_id: Any, token: str) -> list[dict[str, Any]]:
    """The full `session_events` log this role may see (§40.4's `redact`, same rule the socket
    uses), ordered by `seq_no` — the "nothing rewritten" record this module asserts a prefix of.
    """
    response = await client.get(
        f"/api/v1/sessions/{session_id}/events",
        headers=auth(token),
        params={"after_seq_no": 0, "limit": 500},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert not body["has_more"], "widen the page: this test reads the whole log"
    return sorted(body["items"], key=lambda item: item["seq_no"])


async def _drain_resume(socket: ASGIWebSocket, target_seq_no: int) -> list[int]:
    """Fold `event` frames until `target_seq_no` has been delivered, then confirm silence.

    Returns the `seq_no`s the resumed socket actually delivered, in delivery order — the
    assertion that a resume is *exactly* the tail, no duplicate and no gap.
    """
    delivered: list[int] = []
    while not delivered or delivered[-1] < target_seq_no:
        frame = await socket.receive(DELIVERY_TIMEOUT_S)
        if frame["type"] == "event":
            delivered.append(int(frame["seq_no"]))
    while True:
        try:
            frame = await socket.receive(QUIET_S)
        except TimeoutError:
            return delivered
        if frame["type"] == "event":
            delivered.append(int(frame["seq_no"]))


async def test_a_refresh_restores_the_active_session_and_resumes_with_no_gap_or_duplicate(
    client: httpx.AsyncClient,
    websocket: Callable[..., ASGIWebSocket],
    flow: OperatorFlow,
) -> None:
    token = flow.operator_token

    # -- build up some state the refreshed page must recover ------------------------------------
    assert await flow.advance_call_flow() is True  # `ring`
    assert (await flow.post("/operator/call/answer")).status_code == 200
    assert (await flow.set_field("incident.type", "FIRE")).status_code == 200

    before_events = await _events(client, flow.session_id, token)

    # -- the refreshed page reads its snapshot FIRST, while it is still stale --------------------
    refresh_response = await flow.snapshot()
    assert refresh_response.status_code == 200, refresh_response.text
    snapshot = refresh_response.json()
    assert snapshot["session"]["state"] == "ACTIVE", "a refresh must restore an ACTIVE session"
    incident_id = snapshot["session"]["incident_id"]
    assert snapshot["card"]["values"]["incident.type"] == "FIRE"

    # -- a command commits inside the refresh window (the page is still "reloading") ------------
    assert (await flow.set_field("address.street", "Ленина")).status_code == 200

    target = (await _events(client, flow.session_id, token))[-1]["seq_no"]
    socket = websocket(flow.session_id, token=token)
    async with socket:
        await socket.send_json({"type": "resume", "after_seq_no": snapshot["last_seq_no"]})
        delivered = await _drain_resume(socket, target)

    assert delivered, "the field set inside the refresh window must be replayed"
    assert len(set(delivered)) == len(delivered), "no seq_no delivered twice"
    assert delivered == sorted(delivered), "events must arrive in seq_no order"
    assert min(delivered) == snapshot["last_seq_no"] + 1, "no gap between the cursor and the replay"

    # -- never silently reset: nothing already written disappeared or changed -------------------
    after_events = await _events(client, flow.session_id, token)
    assert_prefix_preserved(before_events, after_events)
    after_snapshot = (await flow.snapshot()).json()
    assert after_snapshot["session"]["state"] == "ACTIVE"
    assert after_snapshot["session"]["incident_id"] == incident_id
    assert after_snapshot["card"]["values"]["incident.type"] == "FIRE"
    assert after_snapshot["card"]["values"]["address.street"] == "Ленина"
    assert EventType.SESSION_ABORTED.value not in {event["event_type"] for event in after_events}
