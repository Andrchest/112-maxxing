"""INV 4 — "The operator card is not auto-filled from ASR" (SPEC §42 item 4, §9; D3, D5).

The invariant has a structural half and a behavioural half, and the structural one is the real
guarantee. A behavioural test can only say "this transcript did not move this card"; a scan of
the code says "no transcript *can* move any card", which is the property SPEC §9 actually asks
for when it makes the trainee the only writer.

**(a) Structural.** Two assertions over `backend/app/application/**`:

1. only five modules call the domain's `set_field` or a *write* method of
   `OperatorCardRepository` — the three trainee card commands
   (`operator/set_card_field.py`, `operator/select_service.py`, `operator/deselect_service.py`)
   and E9's two handoff writers (`handoff/create_handoff.py`, `handoff/prefab_handoff.py`).
   (`sessions/create_session.py` inserts the empty card at session creation and is allow-listed
   for `add` alone.)
2. none of those five modules imports anything transcript-, ASR- or voice-related. They cannot
   read a transcript, so they cannot transcribe one into a card.

Together the two make the path from ASR to the card *absent*, not merely unused.

**(a′) The ASR path itself (E12).** Once the voice path has a real ASR stage, the scan has to run
in the other direction too: not only "no card writer can read a transcript" but "nothing that
*produces* a transcript can reach a card". Two more assertions cover
`backend/app/application/voice/**` and `backend/app/inference/**`:

3. neither package uses any card writer or the `operator_cards` repository attribute;
4. neither package imports the operator-card, DDS or handoff command modules — the modules that
   would let it issue the write indirectly.

`app/application/**` is already swept by assertion 1, which includes `voice/`; `app/inference/**`
is outside that sweep (it is the inference layer, not the application layer) and is added here.

**(b) Behavioural.** Append `ASR_PARTIAL` and `ASR_FINAL` whose text literally contains an
address and a service name — exactly what a naive auto-filler would seize on — and assert that
the card row, the revision count, the `CARD_FIELD_CHANGED` count and the snapshot's card are all
byte-identical before and after.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from app.domain.events.types import EventType
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND = Path(__file__).resolve().parents[2]
APPLICATION = BACKEND / "app" / "application"
#: The two packages that own the ASR path (E12): the voice turn stages and the model adapters.
ASR_PATH_ROOTS: tuple[Path, ...] = (
    APPLICATION / "voice",
    BACKEND / "app" / "inference",
)

#: Modules whose import would let the ASR path reach a card, a service selection or a handoff
#: *indirectly* — by calling the use case rather than the repository. Dotted prefixes, matched
#: against the module a `from … import …` names.
CARD_COMMAND_MODULES: tuple[str, ...] = (
    "app.application.operator.set_card_field",
    "app.application.operator.select_service",
    "app.application.operator.deselect_service",
    "app.application.operator.views",
    "app.application.handoff",
    "app.application.dds",
    "app.application.ports.operator_card_repository",
    "app.domain.layers.operator_card",
)

# ---------------------------------------------------------------------------------------------
# (a) Structural
# ---------------------------------------------------------------------------------------------

#: The domain function that mutates a card, and the repository methods that persist a mutation.
#: `get` and `list_revisions` are reads and are deliberately absent.
CARD_WRITERS: frozenset[str] = frozenset({"set_field", "save", "add", "add_revision"})

#: The one repository attribute those methods are reached through on a Unit of Work.
CARD_REPOSITORY_ATTRIBUTE = "operator_cards"

#: `module path relative to app/application` -> the card writers it may use, and why.
ALLOWED_WRITERS: dict[str, frozenset[str]] = {
    # The three trainee card commands (SPEC §9: "the trainee is the only writer").
    "operator/set_card_field.py": frozenset({"set_field", "save", "add_revision"}),
    "operator/select_service.py": frozenset({"set_field", "save", "add_revision"}),
    "operator/deselect_service.py": frozenset({"set_field", "save", "add_revision"}),
    # Session creation inserts the *empty* card row; it writes no value and makes no revision.
    "sessions/create_session.py": frozenset({"add"}),
    # E9: `createHandoff` freezes the card into a `HandoffSnapshot` and writes
    # `recipients.comment` first (`CreateHandoffRequest.comment_ru`), which `openapi.yaml`
    # requires to be a card field "rather than a side channel around it".
    "handoff/create_handoff.py": frozenset({"set_field", "save", "add_revision"}),
    # E9: a `role_chain` of `[DDS]` has no 112 stage, so the scenario's
    # `expected_response.prefab_handoff` is written onto the card at stage start and frozen from
    # there (D6, §30.5). The values come from the scenario file; see the module docstring.
    "handoff/prefab_handoff.py": frozenset({"set_field", "save", "add_revision"}),
}

#: Substrings that mark a module as transcript-, ASR- or voice-related. A card writer that
#: imported any of them could read what the caller said, which is the whole failure mode.
VOICE_TOKENS: tuple[str, ...] = (
    "transcript",
    "asr",
    "stt",
    "tts",
    "voice",
    "speech",
    "utterance",
    "dialogue",
    "audio",
    "inference",
)


def _application_modules() -> list[Path]:
    return sorted(path for path in APPLICATION.rglob("*.py") if path.name != "__init__.py")


def _relative(path: Path) -> str:
    return path.relative_to(APPLICATION).as_posix()


def _card_writers_used(path: Path) -> set[str]:
    """Every card-writing name this module *uses* — imported, called, or reached on the repo.

    A definition does not count: `ports/operator_card_repository.py` declares `save` and
    `add_revision` and is not a writer, and neither is the fake that implements them.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    used: set[str] = set()
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            used.update(alias.name for alias in node.names if alias.name in CARD_WRITERS)
        elif isinstance(node, ast.Attribute) and node.attr in CARD_WRITERS:
            # `<something>.operator_cards.<writer>` — the only way to reach the repository.
            inner = node.value
            if isinstance(inner, ast.Attribute) and inner.attr == CARD_REPOSITORY_ATTRIBUTE:
                used.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in CARD_WRITERS
            and node.func.id not in defined
        ):
            used.add(node.func.id)
    return used


def _imported_tokens(path: Path) -> set[str]:
    """Every dotted-name part and imported/aliased symbol of every import in the module."""
    tokens: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tokens.update(alias.name.split("."))
                if alias.asname:
                    tokens.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                tokens.update(node.module.split("."))
            for alias in node.names:
                tokens.add(alias.name)
                if alias.asname:
                    tokens.add(alias.asname)
    return tokens


def test_only_the_allow_listed_modules_can_write_a_card() -> None:
    """SPEC §42 test 4, structurally: the set of card writers is the set this file allows."""
    offenders: list[str] = []
    for path in _application_modules():
        relative = _relative(path)
        allowed = ALLOWED_WRITERS.get(relative, frozenset())
        used = _card_writers_used(path)
        forbidden = sorted(used - allowed)
        if forbidden:
            offenders.append(f"{relative}: {forbidden}")
    assert not offenders, (
        "these application modules write the operator card and are not allow-listed in "
        f"backend/tests/invariants/test_inv_04_asr_never_mutates_card.py: {offenders}"
    )


def test_the_scan_actually_sees_the_known_card_writers() -> None:
    """A guard on the guard: a scan that found nothing would pass the test above vacuously."""
    for relative in ALLOWED_WRITERS:
        path = APPLICATION / relative
        assert path.is_file(), f"{relative} is allow-listed but does not exist"
        assert _card_writers_used(path), f"{relative} is allow-listed but writes no card"


@pytest.mark.parametrize(
    "relative",
    [name for name in ALLOWED_WRITERS if not name.startswith("sessions/")],
)
def test_a_card_writer_cannot_reach_a_transcript(relative: str) -> None:
    """The second half of (a): a card writer imports nothing that can tell it what was said."""
    tokens = {token.lower() for token in _imported_tokens(APPLICATION / relative)}
    offenders = sorted(token for token in tokens if any(marker in token for marker in VOICE_TOKENS))
    assert not offenders, (
        f"{relative} imports {offenders}: a module that may write the card must not be able to "
        "read a transcript (SPEC §9, §42 test 4)"
    )


# ---------------------------------------------------------------------------------------------
# (a′) The ASR path (E12)
# ---------------------------------------------------------------------------------------------


def _asr_path_modules() -> list[Path]:
    """Every module of `application/voice/**` and `inference/**`, `__init__.py` included.

    `__init__.py` is *not* skipped here, unlike in `_application_modules`: a package initialiser
    that re-exported a card command would be exactly the hole this scan is for.
    """
    modules: list[Path] = []
    for root in ASR_PATH_ROOTS:
        modules.extend(sorted(root.rglob("*.py")))
    return modules


def _imported_modules(path: Path) -> set[str]:
    """Every dotted module name this file imports, as written."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_the_asr_path_scan_actually_sees_some_modules() -> None:
    """A guard on the guard: an empty sweep would pass the two tests below vacuously."""
    modules = _asr_path_modules()
    assert len(modules) >= 10, f"the ASR-path sweep found only {len(modules)} modules"
    for root in ASR_PATH_ROOTS:
        assert root.is_dir(), f"{root} does not exist"


def test_the_asr_path_writes_no_card() -> None:
    """SPEC §42 test 4 for E12: nothing that produces a transcript can write a card."""
    offenders: list[str] = []
    for path in _asr_path_modules():
        used = sorted(_card_writers_used(path))
        if used:
            offenders.append(f"{path.relative_to(BACKEND).as_posix()}: {used}")
    assert not offenders, (
        "these modules of the ASR path write the operator card, which SPEC §9 reserves for the "
        f"trainee: {offenders}"
    )


def test_the_asr_path_imports_no_card_command() -> None:
    """…and cannot issue the write indirectly either, by calling the use case."""
    offenders: list[str] = []
    for path in _asr_path_modules():
        forbidden = sorted(
            name
            for name in _imported_modules(path)
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in CARD_COMMAND_MODULES
            )
        )
        if forbidden:
            offenders.append(f"{path.relative_to(BACKEND).as_posix()}: {forbidden}")
    assert not offenders, (
        "these modules of the ASR path import a card / service / handoff command module, which "
        f"would let ASR text reach the incident card (SPEC §9, §42 test 4): {offenders}"
    )


# ---------------------------------------------------------------------------------------------
# (b) Behavioural
# ---------------------------------------------------------------------------------------------
#
# The API fixtures live in `tests/api/conftest.py` and `tests/api/operator/conftest.py`; they are
# re-exported here by name rather than through `pytest_plugins`, which cannot register a module
# that is already loaded as a real conftest. `clean_database` is deliberately NOT re-exported —
# it is autouse over there, and the structural tests above must stay database-free; the local
# `clean_api_db` below is its explicitly requested twin.

from tests.api import conftest as _api_fixtures  # noqa: E402
from tests.api.operator import conftest as _operator_fixtures  # noqa: E402

api_settings = _api_fixtures.api_settings
client = _api_fixtures.client
demo_version_id = _api_fixtures.demo_version_id
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
tokens = _api_fixtures.tokens
unit_of_work = _api_fixtures.unit_of_work
users = _api_fixtures.users

connected = _operator_fixtures.connected
container = _operator_fixtures.container
flow = _operator_fixtures.flow
idempotency = _operator_fixtures.idempotency
interview = _operator_fixtures.interview
ringing = _operator_fixtures.ringing
uow_factory = _operator_fixtures.uow_factory

OperatorFlow = _operator_fixtures.OperatorFlow

_TRUNCATE = text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")


@pytest.fixture
async def clean_api_db(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """`tests.api.conftest.clean_database`, requested explicitly instead of autouse."""
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)


#: The text a naive auto-filler would mine: a street, a house number and a service name, in the
#: Russian a caller would actually use.
ADDRESS_AND_SERVICE_RU = (
    "Пожар по адресу улица Ленина, дом 5, квартира 12 — вызывайте пожарную охрану, "
    "нужна скорая помощь и полиция"
)


@pytest.mark.integration
async def test_appending_asr_events_changes_nothing_about_the_card(
    clean_api_db: None, interview: OperatorFlow
) -> None:
    """SPEC §42 test 4, behaviourally: the transcript names the address; the card stays empty."""
    # Give the card one real trainee entry first, so "unchanged" is a non-trivial statement.
    assert (await interview.set_field("incident.type", "FIRE")).status_code == 200

    before_card = (await interview.get("/operator/card")).json()
    before_revisions = (await interview.get("/operator/card/revisions")).json()
    before_snapshot = (await interview.snapshot()).json()["card"]
    before_changes = (await interview.event_types()).count("CARD_FIELD_CHANGED")

    await interview.append_asr(EventType.ASR_PARTIAL, ADDRESS_AND_SERVICE_RU, turn_index=1)
    await interview.append_asr(EventType.ASR_FINAL, ADDRESS_AND_SERVICE_RU, turn_index=1)
    # …and let the simulation loop run, since the call flow is the one component that reacts to
    # an `ASR_FINAL` at all. It fires `begin_interview` and nothing else — never a card write.
    await interview.advance_call_flow()

    after_card = (await interview.get("/operator/card")).json()
    after_revisions = (await interview.get("/operator/card/revisions")).json()
    after_snapshot = (await interview.snapshot()).json()["card"]
    after_changes = (await interview.event_types()).count("CARD_FIELD_CHANGED")

    assert after_card == before_card, "the ASR text reached the card"
    assert after_revisions == before_revisions, "the ASR text produced a card revision"
    assert after_snapshot == before_snapshot, "the snapshot's card changed under ASR"
    assert after_changes == before_changes, "the ASR text produced a CARD_FIELD_CHANGED"
    assert after_card["values"] == {"incident.type": "FIRE"}, "only the trainee's entry is there"


@pytest.mark.integration
async def test_no_card_revision_row_has_a_model_actor(
    clean_api_db: None, interview: OperatorFlow
) -> None:
    """The database's own CHECK: `incident_card_revisions.actor_type` admits no `MODEL` row.

    This is the last line of the same defence — even a use case that tried would be refused by
    PostgreSQL (`20-db-schema.md` §20.4, `CARD_REVISION_ACTOR_TYPES`).
    """
    await interview.set_field("address.house", "5")
    await interview.append_asr(EventType.ASR_FINAL, ADDRESS_AND_SERVICE_RU)

    async with interview.container.unit_of_work() as uow:
        actors = await uow.session.execute(
            sa.text("SELECT DISTINCT actor_type FROM incident_card_revisions")
        )
        rows = sorted(row[0] for row in actors.all())
        await uow.commit()
    assert rows == ["TRAINEE"]
