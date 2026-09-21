"""INV 13 at the API level — "Refresh does not lose active incident state" (SPEC §42 item 13, §39).

`40-realtime-protocol.md` §40.5 "Browser refresh" describes the whole contract in four steps: the
page loads with no in-memory state, it reads `GET /api/v1/sessions/{id}/snapshot`, it opens a
WebSocket and sends `{"type":"resume","after_seq_no":last_seq_no}`, and the server replays
anything appended between the snapshot read and the subscribe before going live. This file proves
the promise that makes those four steps worth taking: **the state a refreshed client reconstructs
is exactly the state a client that never refreshed has folded.**

The shape of every check here:

* client **A** opens one socket at the start, resumes from `0` and folds every event it is ever
  sent. It never refreshes. It is the reference;
* at three different points, an operator command sequence is interrupted by a *refresh*: read the
  snapshot, **keep playing** (more commands commit while the "page is reloading"), then open a
  **new** socket, resume from `snapshot.last_seq_no` and fold on top of the snapshot;
* the two states must agree on the card values, `stage_state`, `call_state.phase` and the folded
  `last_seq_no`, and the refreshed client's `seq_no` stream must be *exactly* A's tail — no
  duplicate, no gap.

Commands committing between the snapshot read and the resume is what makes this a test rather than
a tautology: it is the only window in which a snapshot that read `last_seq_no` outside its own
transaction can lose an event, which is the failure §42 item 13 is about.

The second half does the same after a **backend restart**: a brand-new `Container` — new
`AsyncEngine`, new Redis client, new `create_app` — over the same database, exactly as
§40.5 "Backend restart" describes ("no event is lost, because every event was committed to
PostgreSQL before it was ever published"). Simulated time must not reset either:
`monotonic_offset_ms` is derived from the persisted `started_at` (D7), so the new process must
report *at least* what the dead one did, never `0`.

No port is bound: both the original and the restarted application are driven in process through
`httpx.ASGITransport` and the ASGI WebSocket harness of `tests/api/realtime/conftest.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import redis.asyncio as redis_asyncio
from app.api.container import Container
from app.api.main import create_app
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.events.types import EventType
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

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

pytestmark = pytest.mark.integration

#: How long a drain waits for an event that the database says the socket must still deliver.
DELIVERY_TIMEOUT_S = 10.0

#: How long a drain listens for a frame that must NOT arrive (a duplicate, or a stale replay).
QUIET_S = 0.2


# ---------------------------------------------------------------------------------------------
# The client-side fold — what a browser keeps in memory between events
# ---------------------------------------------------------------------------------------------


@dataclass
class Folded:
    """The four facts SPEC §42 item 13 calls "active incident state", folded from events.

    Deliberately assembled by a *client-side* fold rather than read back from the server: the
    invariant is that a refreshed client reconstructs the same thing, so the reconstruction has
    to happen here, from the frames the socket actually delivered.
    """

    card_values: dict[str, Any] = field(default_factory=dict)
    stage_state: str | None = None
    call_phase: str = "NO_CALL"
    seq_nos: list[int] = field(default_factory=list)

    @property
    def last_seq_no(self) -> int:
        """The client's cursor: the highest `seq_no` it has folded."""
        return max(self.seq_nos, default=0)

    @property
    def comparable(self) -> tuple[Any, ...]:
        """What two clients of the same role must agree on, whatever route they took to it."""
        filled = {key: value for key, value in self.card_values.items() if value is not None}
        return (filled, self.stage_state, self.call_phase, self.last_seq_no)

    def apply(self, frame: dict[str, Any]) -> None:
        """Fold one `event` frame (§40.2), exactly as the console's reducer would."""
        self.seq_nos.append(int(frame["seq_no"]))
        event_type, payload = frame["event_type"], frame["payload"]
        if event_type == EventType.ROLE_STAGE_STARTED.value:
            self.stage_state = payload["initial_state"]
        elif event_type == EventType.STAGE_STATE_CHANGED.value:
            self.stage_state = payload["new_state"]
        elif event_type == EventType.CARD_FIELD_CHANGED.value:
            self.card_values[payload["field_path"]] = payload["new_value"]
        elif event_type == EventType.CALL_RINGING.value:
            self.call_phase = "RINGING"
        elif event_type == EventType.CALL_ANSWERED.value:
            self.call_phase = "CONNECTED"
        elif event_type == EventType.CALL_ENDED.value:
            self.call_phase = "ENDED"


def folded_from_snapshot(snapshot: dict[str, Any]) -> Folded:
    """The state a refreshed page starts from: `getSessionSnapshot`, and nothing else (§40.5)."""
    card = snapshot.get("card") or {}
    return Folded(
        card_values=dict(card.get("values") or {}),
        stage_state=snapshot["stage_state"],
        call_phase=snapshot["call_state"]["phase"],
        seq_nos=[int(snapshot["last_seq_no"])],
    )


async def fold_until(socket: ASGIWebSocket, state: Folded, target_seq_no: int) -> None:
    """Fold frames until `target_seq_no` has been seen, then listen for one that must not come.

    The trailing quiet period is not padding: it is what turns "no duplicate" into an assertion
    rather than a hope, because a redelivered event would arrive right behind the last one.
    """
    while state.last_seq_no < target_seq_no:
        frame = await socket.receive(DELIVERY_TIMEOUT_S)
        if frame["type"] == "event":
            state.apply(frame)
    while True:
        try:
            frame = await socket.receive(QUIET_S)
        except TimeoutError:
            return
        if frame["type"] == "event":
            state.apply(frame)


async def open_live_socket(
    websocket: Callable[..., ASGIWebSocket], session_id: Any, token: str, after_seq_no: int
) -> ASGIWebSocket:
    """§40.5 steps 3-4: open, `resume` from a cursor, and wait for `resume_complete`."""
    socket = websocket(session_id, token=token)
    await socket.__aenter__()
    await socket.send_json({"type": "resume", "after_seq_no": after_seq_no})
    return socket


async def visible_last_seq_no(client: httpx.AsyncClient, session_id: Any, token: str) -> int:
    """The highest `seq_no` this role's socket must have delivered, straight from PostgreSQL.

    `listSessionEvents` applies the *same* `redact` as the socket (§40.4 "the same function serves
    `GET /api/v1/sessions/{id}/events`"), so the last item of this page is the frame a fold is
    waiting for — which is why the drains below can be deterministic instead of timed.
    """
    response = await client.get(
        f"/api/v1/sessions/{session_id}/events",
        headers=auth(token),
        params={"after_seq_no": 0, "limit": 200},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert not response.json()["has_more"], "widen the page: this test folds the whole log"
    return max((int(item["seq_no"]) for item in items), default=0)


@dataclass
class LiveClient:
    """Client A: one socket, opened once, folding everything (§40.5's "never refreshed")."""

    socket: ASGIWebSocket
    state: Folded


@pytest.fixture
async def live_client(
    websocket: Callable[..., ASGIWebSocket], flow: OperatorFlow
) -> AsyncIterator[LiveClient]:
    """An operator socket resumed from `0` and left open for the whole test."""
    socket = await open_live_socket(websocket, flow.session_id, flow.operator_token, 0)
    try:
        yield LiveClient(socket=socket, state=Folded())
    finally:
        await socket.aclose()


async def assert_refresh_reconstructs(
    *,
    client: httpx.AsyncClient,
    websocket: Callable[..., ASGIWebSocket],
    session_id: Any,
    token: str,
    live: LiveClient,
    snapshot: dict[str, Any],
    label: str,
) -> None:
    """The heart of the invariant, for one refresh point.

    `snapshot` was read *before* the most recent commands, so the refreshed client has to recover
    them through its resume — the window in which an event can be lost.
    """
    target = await visible_last_seq_no(client, session_id, token)
    await fold_until(live.socket, live.state, target)

    refreshed = folded_from_snapshot(snapshot)
    cursor = int(snapshot["last_seq_no"])
    socket = await open_live_socket(websocket, session_id, token, cursor)
    try:
        await fold_until(socket, refreshed, target)
    finally:
        await socket.aclose()

    assert refreshed.comparable == live.state.comparable, (
        f"{label}: snapshot + resume must reconstruct the uninterrupted client's state"
    )
    replayed = [seq_no for seq_no in refreshed.seq_nos if seq_no != cursor]
    assert replayed == [seq_no for seq_no in live.state.seq_nos if seq_no > cursor], (
        f"{label}: the resumed stream must be exactly the tail of the live one"
    )
    assert len(set(replayed)) == len(replayed), f"{label}: no seq_no may be delivered twice"
    assert replayed == sorted(replayed), f"{label}: events must arrive in seq_no order"


# ---------------------------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------------------------


async def test_a_refresh_at_three_points_reconstructs_the_live_client_exactly(
    client: httpx.AsyncClient,
    websocket: Callable[..., ASGIWebSocket],
    live_client: LiveClient,
    flow: OperatorFlow,
) -> None:
    """§40.5 steps 2-4, three times, with commands committing inside the refresh window."""
    token = flow.operator_token

    async def refresh(label: str) -> dict[str, Any]:
        response = await flow.snapshot()
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        assert body["stage_state"] is not None, f"{label}: the snapshot must name the stage state"
        return body

    # --- point 1: the call is answered; the interview begins while the page reloads -----------
    assert await flow.advance_call_flow() is True  # `ring`
    assert (await flow.post("/operator/call/answer")).status_code == 200
    snapshot = await refresh("answered")
    await flow.append_asr(EventType.ASR_FINAL, "Горит квартира на улице Ленина, дом 5")
    assert await flow.advance_call_flow() is True  # `begin_interview`
    await assert_refresh_reconstructs(
        client=client,
        websocket=websocket,
        session_id=flow.session_id,
        token=token,
        live=live_client,
        snapshot=snapshot,
        label="refresh while the interview begins",
    )

    # --- point 2: two card fields are filled; a third lands inside the window ------------------
    assert (await flow.set_field("incident.type", "FIRE")).status_code == 200
    assert (await flow.set_field("address.street", "Ленина")).status_code == 200
    snapshot = await refresh("card filled")
    assert (await flow.set_field("address.house", "5")).status_code == 200
    await assert_refresh_reconstructs(
        client=client,
        websocket=websocket,
        session_id=flow.session_id,
        token=token,
        live=live_client,
        snapshot=snapshot,
        label="refresh while a card field is written",
    )

    # --- point 3: a service is selected; a deselect and a field land inside the window ---------
    assert (await flow.select("FIRE_RESCUE")).status_code == 200
    snapshot = await refresh("service selected")
    assert (await flow.select("AMBULANCE")).status_code == 200
    assert (await flow.deselect("FIRE_RESCUE")).status_code == 200
    assert (await flow.set_field("caller.phone", "+79990000000")).status_code == 200
    await assert_refresh_reconstructs(
        client=client,
        websocket=websocket,
        session_id=flow.session_id,
        token=token,
        live=live_client,
        snapshot=snapshot,
        label="refresh while the recipient services change",
    )

    # The fold is not vacuous: the invariant would hold trivially over an empty state.
    assert live_client.state.card_values["incident.type"] == "FIRE"
    assert live_client.state.call_phase == "CONNECTED"
    assert live_client.state.stage_state == "INTERVIEW"
    assert len(live_client.state.seq_nos) >= 10


# ---------------------------------------------------------------------------------------------
# Backend restart
# ---------------------------------------------------------------------------------------------


class RestartedBackend:
    """A second "process": new engine, new Redis client, new container, new ASGI app.

    Only PostgreSQL, Redis and the wall clock survive — which is exactly what survives a real
    restart. Nothing is carried over in memory, so anything the restarted backend answers it
    derived from the database (D5, D7).
    """

    def __init__(self, settings: Settings, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        self.redis: redis_asyncio.Redis = redis_asyncio.from_url(
            settings.redis_url, decode_responses=True
        )
        self.container = Container(
            settings,
            engine=self.engine,
            session_factory=create_session_factory(self.engine),
            redis=self.redis,
            owns_engine=False,
            owns_redis=False,
        )
        self.app = create_app(self.container)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://api"
        )

    def websocket(self, session_id: Any, *, token: str | None = None) -> ASGIWebSocket:
        """The same in-loop harness, over the restarted application."""
        params = {} if token is None else {"token": token}
        return ASGIWebSocket(self.app, f"/api/v1/ws/sessions/{session_id}", params)

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.redis.aclose()
        await self.engine.dispose()


@pytest.fixture
async def restarted(
    api_settings: Settings, migrated_engine: AsyncEngine
) -> AsyncIterator[RestartedBackend]:
    """The backend that comes up after the one the test started with went away."""
    url = migrated_engine.url.render_as_string(hide_password=False)
    backend = RestartedBackend(api_settings, url)
    try:
        yield backend
    finally:
        await backend.aclose()


async def test_a_restart_loses_no_event_and_does_not_reset_simulated_time(
    client: httpx.AsyncClient,
    websocket: Callable[..., ASGIWebSocket],
    live_client: LiveClient,
    flow: OperatorFlow,
    restarted: RestartedBackend,
) -> None:
    """§40.5 "Backend restart" plus D7's "sim time is derived from the persisted `started_at`"."""
    token = flow.operator_token

    # --- the first process: play up to an answered call and a partly filled card --------------
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    assert (await flow.set_field("incident.type", "FIRE")).status_code == 200
    before = (await flow.snapshot()).json()
    assert before["session"]["monotonic_offset_ms"] >= 0

    target = await visible_last_seq_no(client, flow.session_id, token)
    await fold_until(live_client.socket, live_client.state, target)

    # --- the restart: everything in memory is gone; the socket is not reused -------------------
    await live_client.socket.aclose()

    after = await restarted.client.get(
        f"/api/v1/sessions/{flow.session_id}/snapshot", headers=auth(token)
    )
    assert after.status_code == 200, after.text
    snapshot = after.json()

    assert snapshot["session"]["started_at"] == before["session"]["started_at"], (
        "a restart must not restart the session"
    )
    assert snapshot["session"]["monotonic_offset_ms"] >= before["session"]["monotonic_offset_ms"], (
        "simulated time is derived from the persisted `started_at` (D7) and cannot go backwards"
    )
    assert snapshot["last_seq_no"] == before["last_seq_no"], "no event was lost by the restart"
    assert snapshot["stage_state"] == before["stage_state"]
    assert snapshot["call_state"]["phase"] == "CONNECTED"

    # --- the reconnect: resume over the NEW process, then keep playing on it -------------------
    socket = await open_live_socket(
        restarted.websocket, flow.session_id, token, int(snapshot["last_seq_no"])
    )
    try:
        reconnected = folded_from_snapshot(snapshot)
        set_field = await restarted.client.put(
            f"/api/v1/sessions/{flow.session_id}/operator/card/field",
            headers=auth(token),
            json={"field_path": "address.street", "new_value": "Ленина"},
        )
        assert set_field.status_code == 200, set_field.text

        target = await visible_last_seq_no(restarted.client, flow.session_id, token)
        await fold_until(socket, reconnected, target)
    finally:
        await socket.aclose()

    # The pre-restart fold, advanced by hand with the one command the new process accepted, is
    # what the reconnected client must have reconstructed.
    expected = live_client.state
    expected.card_values["address.street"] = "Ленина"
    assert reconnected.comparable[:3] == expected.comparable[:3]
    assert reconnected.last_seq_no == target

    final = (
        await restarted.client.get(
            f"/api/v1/sessions/{flow.session_id}/snapshot", headers=auth(token)
        )
    ).json()
    assert final["session"]["monotonic_offset_ms"] >= snapshot["session"]["monotonic_offset_ms"]
    assert final["card"]["values"]["incident.type"] == "FIRE", (
        "the pre-restart card value survived the restart"
    )
