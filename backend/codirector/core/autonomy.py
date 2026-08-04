"""Autonomy levels — build spec v1.0 §2 Scope / D-15 / R-AUT-*.
OBSERVE is the only legal startup value (R-AUT-01); CO_DIRECT never persists
across a restart (R-AUT-02) and is never reached except via an explicit
creator UI action (R-AUT-03) — enforced in api/routes.py, not here.
"""
from enum import Enum


class AutonomyLevel(str, Enum):
    OBSERVE = "OBSERVE"
    ASSIST = "ASSIST"
    CO_DIRECT = "CO_DIRECT"


_ORDER = {AutonomyLevel.OBSERVE: 0, AutonomyLevel.ASSIST: 1, AutonomyLevel.CO_DIRECT: 2}


def is_escalation(current: AutonomyLevel, requested: AutonomyLevel) -> bool:
    return _ORDER[requested] > _ORDER[current]
