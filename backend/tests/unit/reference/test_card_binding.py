"""Card ↔ classifier binding coverage (D18 applied; I3 B1 §4, owed by E3a′).

The binding rule makes every routing option of `reference/card-schema/v2.yaml` a classifier
identifier — the resolver (E2b) reads only these codes and never parses labels — so the binding is
checked here as data rather than trusted:

1. every routing-relevant option (not `routing: none`) resolves: a «Что случилось» code is a
   classifier `group_no`; an address code is a catalog `okrug`/`district`; a questionnaire code is
   either a flag key of `v046_24.columns.json` or признак text(s) of *its* group's rows (101 →
   group 1, 104 → group 13 «Запах газа», Взрыв → group 3 «Взрывы»), matched casefolded and
   whitespace-collapsed;
2. every first-level признак of those three groups (the classifier's «Где» / «Признаки
   происшествия» / «Где взрыв» column) has a chip, and the rows the card cannot reach are exactly
   the ones whose deeper признак sits behind a branch no screenshot shows (the v2.yaml TODOs) —
   pinned below, so a new chip or a lost one changes this test.

Run with `-s` to print the coverage summary.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from app.domain.layers.card_schema import CardFieldSpec, parse_card_schema

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_DIR = REPO_ROOT / "reference"
V2 = parse_card_schema(
    yaml.safe_load((REFERENCE_DIR / "card-schema" / "v2.yaml").read_text(encoding="utf-8"))
)
ROWS = json.loads((REFERENCE_DIR / "classifier" / "v046_24.json").read_text(encoding="utf-8"))
COLUMNS = json.loads(
    (REFERENCE_DIR / "classifier" / "v046_24.columns.json").read_text(encoding="utf-8")
)
SERVICES = yaml.safe_load((REFERENCE_DIR / "services" / "v1.yaml").read_text(encoding="utf-8"))

HIDDEN = "Не отображается оператору 112"
FLAGS = frozenset(COLUMNS["flags"])
GROUPS_BY_PREFIX = {"q.fire.": 1, "q.gas.": 13, "q.explosion.": 3}
TYPE_CODE_BY_PREFIX = {"q.fire.": "1", "q.gas.": "13", "q.explosion.": "3"}

#: Group-1 признаки the card has no chip for — each behind a branch no screenshot shows (v2.yaml
#: TODOs: the «Здание / объект» / «Опасный объект» branches, the «Метро» / «МЦК, МЦД» follow-ups).
GROUP_1_UNCHIPPED = frozenset(
    {
        "вагон/поезд,",
        "станция/вестибюль, тоннель / перегон, переход, платформа, эскалатор, прочее",
        "учебное",
        "лечебное",
        "административное",
        "общестенное место",
        "газопровод",
        "газохранилище",
        "нефтепровод",
        "нефтехранилище",
        "наземные коммуникации",
        "подземные коммуникации",
        "гидросооружение",
        "производство",
        "азс",
        "прочие объекты",
    }
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _rows(group_no: int) -> list[dict[str, object]]:
    return [row for row in ROWS["rows"] if row["group_no"] == group_no]


def _features(row: dict[str, object]) -> list[str]:
    return [str(feature) for feature in row["features"]]  # type: ignore[attr-defined]


def _fields(prefix: str) -> Iterable[CardFieldSpec]:
    return (spec for spec in V2.fields if spec.field_path.startswith(prefix))


def _chip_texts(prefix: str) -> set[str]:
    return {
        _norm(text)
        for spec in _fields(prefix)
        for option in spec.options or ()
        for text in option.classifier_feature_texts
        if option.code not in FLAGS
    }


def test_every_routing_option_resolves_to_a_classifier_identifier() -> None:
    group_numbers = {str(group["group_no"]) for group in ROWS["groups"]}
    okrugs = {s["okrug"] for s in SERVICES["services"] if s["kind"] == "PREFECTURE"}
    districts = {s["district"] for s in SERVICES["services"] if s["kind"] == "DISTRICT"}
    group_texts = {
        group: {
            _norm(text)
            for row in _rows(group)
            for text in (*_features(row), *row["extra_features"])  # type: ignore[misc]
        }
        for group in GROUPS_BY_PREFIX.values()
    }
    unbound: list[str] = []
    bound = routed = 0
    for spec in V2.fields:
        if not spec.routing_relevant or spec.options is None:
            continue
        for option in spec.options:
            if option.routing == "none":
                continue
            routed += 1
            path, code = spec.field_path, option.code
            if path == "incident.types":
                # `<group_no>` or, for a group several entries open, `<group_no>:<slug>` (manager
                # decision on B1, D21); a listed признак must be one of that group's.
                group = code.split(":", 1)[0]
                features = option.classifier_features or ()
                ok = group in group_numbers and all(
                    _norm(text) in _group_texts(int(group)) for text in features
                )
            elif path == "address.okrug":
                ok = code in okrugs
            elif path == "address.district":
                ok = code in districts
            elif code in FLAGS:
                ok = option.classifier_features is None
            else:
                prefix = next(p for p in GROUPS_BY_PREFIX if path.startswith(p))
                texts = group_texts[GROUPS_BY_PREFIX[prefix]]
                ok = bool(option.classifier_feature_texts) and all(
                    _norm(text) in texts for text in option.classifier_feature_texts
                )
            if ok:
                bound += 1
            else:
                unbound.append(f"{path}: {code!r}")
    print(f"\nbinding: {bound}/{routed} routing options resolve to a classifier identifier")
    assert unbound == []
    assert routed > 0


def _group_texts(group_no: int) -> set[str]:
    return {
        _norm(text)
        for row in _rows(group_no)
        for text in (*_features(row), *row["extra_features"])  # type: ignore[misc]
    }


def test_the_what_happened_codes_follow_the_shared_group_rule() -> None:
    """Manager decision on B1 (D21): a group opened by one entry is coded `<group_no>`; a group
    several entries open codes each `<group_no>:<slug>` (ASCII slug, unique in the field)."""
    types = V2.spec("incident.types")
    assert types is not None and types.options is not None
    routed = [option for option in types.options if option.routing != "none"]
    by_group: dict[str, list[str]] = {}
    for option in routed:
        by_group.setdefault(option.code.split(":", 1)[0], []).append(option.code)
    shared = {group: codes for group, codes in by_group.items() if len(codes) > 1}
    for group, codes in by_group.items():
        if group not in shared:
            assert codes == [group]
    for codes in shared.values():
        assert all(re.fullmatch(r"\d+:[a-z0-9_]+", code) for code in codes), codes
    assert len({option.code for option in routed}) == len(routed)
    assert sorted(shared) == ["10", "11", "23", "7"]
    print(f"\nshared groups: {dict(sorted(shared.items()))}")


def test_every_first_level_classifier_feature_has_a_chip() -> None:
    for prefix, group in GROUPS_BY_PREFIX.items():
        chips = _chip_texts(prefix)
        first = {_norm(_features(row)[0]) for row in _rows(group) if _features(row)[0] != HIDDEN}
        assert first <= chips, (group, sorted(first - chips))


def test_the_unreachable_rows_are_exactly_the_unscreenshotted_branches() -> None:
    summary: list[str] = []
    for prefix, group in GROUPS_BY_PREFIX.items():
        chips = _chip_texts(prefix)
        shown = [row for row in _rows(group) if _features(row)[0] != HIDDEN]
        missing = {
            _norm(feature)
            for row in shown
            for feature in _features(row)
            if feature.strip() and _norm(feature) not in chips
        }
        reachable = [
            row for row in shown if all(_norm(f) in chips for f in _features(row) if f.strip())
        ]
        summary.append(
            f"group {group}: {len(reachable)}/{len(shown)} displayed rows reachable, "
            f"{len(missing)} признаки without a chip"
        )
        if group == 1:
            assert missing == GROUP_1_UNCHIPPED
        else:
            # 104 and Взрыв: every first-level признак has a chip (test above); what is missing is
            # only the second level, which no screenshot shows.
            first_level = {_norm(_features(row)[0]) for row in shown}
            assert missing and not missing & first_level
        # the questionnaire hangs on the «Что случилось» entry that opens its group
        types = V2.spec("incident.types")
        assert types is not None and TYPE_CODE_BY_PREFIX[prefix] in types.option_codes
    print("\n" + "\n".join(summary))


def test_the_header_flags_carry_the_classifier_flag_keys() -> None:
    expected = {
        "flags.casualties": "casualties",
        "flags.ambulance_refused": "casualties_not_on_site",
        "flags.blocked": "no_access",
    }
    for path, flag in expected.items():
        spec = V2.spec(path)
        assert spec is not None and spec.routing_relevant
        assert [option.code for option in spec.options or ()] == [flag]
        assert flag in FLAGS
