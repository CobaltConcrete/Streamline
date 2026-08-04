"""Stream phase inference — build spec v1.0 §5.5. With D-3 (no gameplay
signal), phase is derived from three inputs in a fixed priority order: OBS
active scene (authoritative), VAD/final-transcript silence gap (refines
ACTIVE into speaking/silent), and chat velocity (advisory-only, feeds
urgency elsewhere, never phase itself — so it isn't modeled here at all)."""
from enum import Enum

_DEFAULT_SPEECH_GAP_MS = 1200.0


class Phase(str, Enum):
    UNKNOWN = "unknown"
    STARTING = "starting"
    ACTIVE_SPEAKING = "active_speaking"
    ACTIVE_SILENT = "active_silent"
    BREAK = "break"
    ENDING = "ending"


class SceneRole(str, Enum):
    """What a creator-configured OBS scene *means* for phase purposes. ACTIVE
    scenes get refined into ACTIVE_SPEAKING/ACTIVE_SILENT by the VAD/transcript
    gap; the other roles are authoritative as-is (§5.5: "OBS active scene ...
    Authoritative")."""

    ACTIVE = "active"
    BREAK = "break"
    STARTING = "starting"
    ENDING = "ending"


_ROLE_TO_TERMINAL_PHASE = {
    SceneRole.BREAK: Phase.BREAK,
    SceneRole.STARTING: Phase.STARTING,
    SceneRole.ENDING: Phase.ENDING,
}

SAFE_WINDOWS = frozenset({Phase.ACTIVE_SILENT, Phase.BREAK, Phase.STARTING})


def is_safe_window(phase: Phase) -> bool:
    return phase in SAFE_WINDOWS


class PhaseEngine:
    def __init__(self, scene_roles: dict[str, SceneRole], speech_gap_ms: float = _DEFAULT_SPEECH_GAP_MS) -> None:
        self._scene_roles = scene_roles
        self._speech_gap_ms = speech_gap_ms
        self._current_scene: str | None = None
        self._obs_connected = False
        self._last_speech_final_time: float | None = None

    def on_obs_state(self, program_scene: str) -> None:
        self._current_scene = program_scene
        self._obs_connected = True

    def on_obs_disconnected(self) -> None:
        # R-CTX-06: UNKNOWN is the state on OBS disconnect.
        self._obs_connected = False

    def on_transcript_final(self, now: float) -> None:
        self._last_speech_final_time = now

    def current_phase(self, now: float) -> Phase:
        if not self._obs_connected or self._current_scene is None:
            return Phase.UNKNOWN
        role = self._scene_roles.get(self._current_scene)
        if role is None:
            # R-CTX-06: an unmapped active scene also defaults to UNKNOWN,
            # i.e. the most conservative behaviour, never a guess.
            return Phase.UNKNOWN
        if role in _ROLE_TO_TERMINAL_PHASE:
            return _ROLE_TO_TERMINAL_PHASE[role]

        # role is ACTIVE: refine via the VAD/final-transcript silence gap.
        if self._last_speech_final_time is None:
            return Phase.ACTIVE_SPEAKING  # no speech yet this session; assume active
        gap_ms = (now - self._last_speech_final_time) * 1000
        return Phase.ACTIVE_SILENT if gap_ms >= self._speech_gap_ms else Phase.ACTIVE_SPEAKING
