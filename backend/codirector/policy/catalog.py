"""Loads and validates config/action_catalog.yaml — build spec v1.0 §4.5, §5.2.
Deny by default: an action_id not present here can never execute (R-CFG-02,
R-OBS-03). Unknown action `type` values are a Pydantic Literal mismatch, which
already satisfies "refuses to load" for R-CFG-02.
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator


class ActionType(str, Enum):
    OVERLAY_TEXT = "overlay_text"
    SCENE_SWITCH = "scene_switch"
    ITEM_VISIBILITY = "item_visibility"
    FILTER_TOGGLE = "filter_toggle"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    # HIGH intentionally does not exist here: high-risk operations are never
    # catalogued at all (§2 "Do not build this" / §9), so there is nothing for
    # the policy engine to allow even if a proposal named one.


class ActionTarget(BaseModel):
    input_name: str | None = None  # overlay_text
    scene_name: str | None = None  # scene_switch, item_visibility
    item_name: str | None = None  # item_visibility
    source_name: str | None = None  # filter_toggle
    filter_name: str | None = None  # filter_toggle


class ActionLimits(BaseModel):
    max_length: int | None = None
    duration_ms: int | None = None
    cooldown_s: float
    max_per_session: int


class ActionSpec(BaseModel):
    id: str
    type: ActionType
    risk: RiskLevel
    target: ActionTarget
    limits: ActionLimits
    reversible: bool = True
    requires_confirmation: bool = False
    # Runtime fields, set by resolve_targets() at startup (R-OBS-03). Not part
    # of the YAML file — mutated in place after load, never at parse time.
    enabled: bool = True
    disabled_reason: str | None = None

    @model_validator(mode="after")
    def _target_matches_type(self) -> "ActionSpec":
        required = {
            ActionType.OVERLAY_TEXT: ["input_name"],
            ActionType.SCENE_SWITCH: ["scene_name"],
            ActionType.ITEM_VISIBILITY: ["scene_name", "item_name"],
            ActionType.FILTER_TOGGLE: ["source_name", "filter_name"],
        }[self.type]
        missing = [f for f in required if getattr(self.target, f) is None]
        if missing:
            raise ValueError(f"action {self.id!r} of type {self.type} missing target fields: {missing}")
        return self


class ActionCatalog(BaseModel):
    version: int
    actions: list[ActionSpec]

    @model_validator(mode="after")
    def _action_ids_are_unique(self) -> "ActionCatalog":
        action_ids = [action.id for action in self.actions]
        duplicates = sorted({action_id for action_id in action_ids if action_ids.count(action_id) > 1})
        if duplicates:
            raise ValueError(f"action ids must be unique, duplicates: {duplicates}")
        return self

    def get(self, action_id: str) -> ActionSpec | None:
        for action in self.actions:
            if action.id == action_id:
                return action
        return None


def load_catalog(path: str | Path) -> ActionCatalog:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ActionCatalog.model_validate(data)


@dataclass
class KnownOBSTargets:
    """Inventory snapshot used to resolve catalog targets at startup (R-OBS-03).
    Built from OBSProvider-implementation-specific inventory calls, which are
    intentionally outside the narrow adapters.base.OBSProvider Protocol."""

    scenes: set[str] = field(default_factory=set)
    inputs: set[str] = field(default_factory=set)
    items_by_scene: dict[str, set[str]] = field(default_factory=dict)
    filters_by_source: dict[str, set[str]] = field(default_factory=dict)


def resolve_targets(catalog: ActionCatalog, known: KnownOBSTargets) -> list[str]:
    """Mutates catalog.actions in place: an unresolvable target disables that
    action (enabled=False, disabled_reason set) and returns a warning per
    disabled action. Never raises — R-OBS-03 requires no crash."""
    warnings: list[str] = []
    for action in catalog.actions:
        reason = None
        t = action.target
        if t.scene_name is not None and t.scene_name not in known.scenes:
            reason = f"scene {t.scene_name!r} not found in OBS"
        elif t.input_name is not None and t.input_name not in known.inputs:
            reason = f"input {t.input_name!r} not found in OBS"
        elif t.item_name is not None and t.item_name not in known.items_by_scene.get(t.scene_name or "", set()):
            reason = f"scene item {t.item_name!r} not found in scene {t.scene_name!r}"
        elif t.filter_name is not None and t.filter_name not in known.filters_by_source.get(t.source_name or "", set()):
            reason = f"filter {t.filter_name!r} not found on source {t.source_name!r}"

        if reason:
            action.enabled = False
            action.disabled_reason = reason
            warnings.append(f"action {action.id!r} disabled: {reason}")
        else:
            action.enabled = True
            action.disabled_reason = None
    return warnings
