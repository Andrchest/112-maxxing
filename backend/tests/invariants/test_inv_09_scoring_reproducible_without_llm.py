"""INV 9 — "Scoring is reproducible without an LLM" (SPEC §42 item 9, §28, §2, D11).

The invariant has a structural half and a behavioural half, and the structural one is the real
guarantee.

**(a) Structural.** An `ast` scan of `app/domain/scoring/**` asserts that the package imports
nothing from `app.inference`, `app.application`, `app.infrastructure`, `app.api`, `app.db` or any
LLM port, and that it never names `datetime.now`, `uuid4`, `random` or a `time` clock. SPEC §2 is
absolute — the LLM "must not calculate numeric scores" — and D11 makes the same promise about I/O
and the clock. A scan of the imports is how "cannot" is checked: a pure function that has no path
to a model cannot be talked into using one.

**(b) Behavioural.** The same `(ScenarioVersion, log)` scored twice, scored after a round trip
through JSON, and scored again over a log that already carries the `SCORING_RULE_EVALUATED`
events a previous run appended (ruling R2), must produce equal reports *and* equal checksums.
The checksum is the machine-checkable form of SPEC §28's "the same event log and scenario version
must always reproduce the same score" — it is what `rescoreSession` compares.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.domain.events.session_event import SessionEvent
from app.domain.scoring.engine import report_checksum, score

from tests.unit.domain.scoring._event_log_builders import (
    MUTATORS,
    demo_scenario,
    good_log,
    mutate,
    with_previous_scoring_events,
)

SCORING_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "domain" / "scoring"

# ---------------------------------------------------------------------------------------------
# (a) Structural
# ---------------------------------------------------------------------------------------------

#: Module prefixes the pure scoring domain may not reach. `app.domain.*` is fine — that is the
#: layer it lives in; everything else is a path to a model, a database or a socket.
FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "app.inference",
    "app.application",
    "app.infrastructure",
    "app.api",
    "app.db",
    "app.config",
    "openai",
    "httpx",
    "sqlalchemy",
)

#: Names that would make a score depend on something other than its two inputs.
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {"now", "utcnow", "uuid4", "uuid1", "monotonic", "perf_counter", "time"}
)

#: Modules that are a clock or a source of randomness, whole.
FORBIDDEN_IMPORTS: frozenset[str] = frozenset({"random", "secrets", "time", "datetime"})


def _scoring_modules() -> list[Path]:
    return sorted(path for path in SCORING_PACKAGE.rglob("*.py") if "__pycache__" not in path.parts)


def test_the_scan_actually_covers_the_package() -> None:
    modules = _scoring_modules()

    assert len(modules) >= 15
    assert {"engine.py", "context.py", "results.py", "rules.py"} <= {p.name for p in modules}


@pytest.mark.parametrize(
    "module", _scoring_modules(), ids=lambda path: str(path.relative_to(SCORING_PACKAGE))
)
def test_scoring_imports_nothing_outside_the_pure_domain(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in FORBIDDEN_IMPORTS, f"{module}:{node.lineno} {alias.name}"
                assert not alias.name.startswith(FORBIDDEN_MODULE_PREFIXES), (
                    f"{module}:{node.lineno} {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            assert node.module not in FORBIDDEN_IMPORTS, f"{module}:{node.lineno} {node.module}"
            assert not node.module.startswith(FORBIDDEN_MODULE_PREFIXES), (
                f"{module}:{node.lineno} {node.module}"
            )
            if node.module.startswith("app.domain.ports") or node.module.endswith(".llm"):
                pytest.fail(f"{module}:{node.lineno} scoring must not reach an LLM port")


@pytest.mark.parametrize(
    "module", _scoring_modules(), ids=lambda path: str(path.relative_to(SCORING_PACKAGE))
)
def test_scoring_never_names_a_clock_or_a_random_source(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            pytest.fail(f"{module}:{node.lineno} names {node.attr}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            pytest.fail(f"{module}:{node.lineno} names {node.id}")


# ---------------------------------------------------------------------------------------------
# (b) Behavioural
# ---------------------------------------------------------------------------------------------


def test_the_same_log_scored_twice_gives_the_same_report() -> None:
    version = demo_scenario()
    events = good_log()

    first = score(version, events)
    second = score(version, good_log())

    assert first == second
    assert report_checksum(first) == report_checksum(second)


@pytest.mark.parametrize("name", sorted(MUTATORS))
def test_every_mutated_log_is_reproducible_too(name: str) -> None:
    version = demo_scenario()

    assert score(version, mutate(name)) == score(version, mutate(name))


def test_a_log_round_tripped_through_json_scores_identically() -> None:
    """D5: the event log is the audit source, and it lives in the database as JSON."""
    version = demo_scenario()
    events = good_log()
    round_tripped = [SessionEvent.model_validate_json(event.model_dump_json()) for event in events]

    original = score(version, events)
    restored = score(version, round_tripped)

    assert report_checksum(original) == report_checksum(restored)
    assert original.results == restored.results


def test_a_log_shuffled_then_sorted_by_seq_no_scores_identically() -> None:
    version = demo_scenario()
    events = good_log()
    scrambled = sorted(reversed(events), key=lambda event: event.seq_no)

    assert score(version, scrambled) == score(version, events)


def test_rescoring_a_log_that_already_contains_scoring_events_reproduces_the_report() -> None:
    """Ruling R2: `SCORING_*` events are the only events after `SESSION_COMPLETED`, and
    `score()` ignores them — so re-scoring the whole stored log is idempotent."""
    version = demo_scenario()
    events = good_log()
    stored = with_previous_scoring_events(events, version)

    original = score(version, events)
    rescored = score(version, stored)

    assert len(stored) > len(events)
    assert rescored == original
    assert report_checksum(rescored) == report_checksum(original)
    assert rescored.computed_from_event_count == len(events)


def test_two_scenario_versions_of_the_same_log_differ_only_by_their_rules() -> None:
    """The scenario version is an input: changing a rule must change the report."""
    version = demo_scenario()
    softened = version.model_copy(
        update={
            "scoring_rules": tuple(
                rule.model_copy(update={"config": {**rule.config, "points": 1.0}})
                if "points" in rule.config
                else rule
                for rule in version.scoring_rules
            )
        }
    )
    events = good_log()

    assert report_checksum(score(version, events)) != report_checksum(score(softened, events))
