"""`leg_for` — the one place that decides which leg a unit hangs on (E9 analyst R4, ruling 3).

Two rules and one consequence, all pinned here:

1. a unit whose service received a handoff leg attaches to **that** leg;
2. a unit whose service received none attaches to the **primary** leg — dispatching an
   off-service unit is allowed, because a trainee's routing mistake is scored, not blocked;
3. therefore an `assignment_id` does **not** imply the unit's service, and nothing downstream may
   use leg → service as a shortcut for unit → service.
"""

from __future__ import annotations

import pytest
from app.application.dds.leg_for import leg_for
from app.domain.common.ids import RoleStageId
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import ServiceType
from app.domain.layers.handoff import HandoffSnapshot

from tests.unit.application.dds.conftest import AMBULANCE, FIRE, POLICE, make_leg, make_resource


def test_a_unit_attaches_to_its_own_services_leg(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """The ambulance goes on the AMBULANCE leg even though FIRE_RESCUE is primary."""
    ambulance = make_resource("СМП-11", AMBULANCE)

    leg = leg_for(ambulance, legs, snapshot)

    assert leg.service_type is AMBULANCE
    assert leg is legs[1]


def test_a_unit_of_the_primary_service_attaches_to_the_primary_leg(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """The obvious case, stated so the two branches are both covered."""
    engine = make_resource("АЦ-1", FIRE)

    assert leg_for(engine, legs, snapshot) is legs[0]


def test_an_off_service_unit_attaches_to_the_primary_leg(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """Ruling 3: a police unit is dispatchable although POLICE received no leg."""
    patrol = make_resource("ППС-204", POLICE)

    leg = leg_for(patrol, legs, snapshot)

    assert leg is legs[0]
    assert leg.service_type is FIRE


def test_the_assignment_id_does_not_imply_the_units_service(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """The cost of "else primary", asserted rather than merely documented.

    Two units on the *same* leg with two different services is exactly the shape that makes
    `service_type_by_resource` necessary on `RESOURCE_DISPATCHED`.
    """
    engine = make_resource("АЦ-1", FIRE)
    patrol = make_resource("ППС-204", POLICE)

    assert leg_for(engine, legs, snapshot) is leg_for(patrol, legs, snapshot)
    assert engine.service_type is not patrol.service_type


def test_the_leg_order_given_does_not_matter(
    snapshot: HandoffSnapshot, legs: list[DDSAssignment]
) -> None:
    """Primary is `recipient_services[0]`'s leg, not the first element of the list."""
    reversed_legs = list(reversed(legs))
    patrol = make_resource("ППС-204", POLICE)

    assert leg_for(patrol, reversed_legs, snapshot).service_type is FIRE


def test_a_single_leg_handoff_takes_everything(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId
) -> None:
    """One recipient service: every unit, of any service, hangs on the one leg there is."""
    only = [make_leg(snapshot, role_stage_id, FIRE)]

    for service in (FIRE, AMBULANCE, POLICE, ServiceType.GAS_SERVICE):
        assert leg_for(make_resource("X", service), only, snapshot) is only[0]


def test_no_leg_at_all_is_a_programming_error(snapshot: HandoffSnapshot) -> None:
    """A handoff always has at least one leg; an empty list is a bug, not a state."""
    with pytest.raises(ValueError, match="no DDS assignment leg"):
        leg_for(make_resource("АЦ-1", FIRE), [], snapshot)
