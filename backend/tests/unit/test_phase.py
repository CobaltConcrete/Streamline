from codirector.core.phase import Phase, PhaseEngine, SceneRole, is_safe_window

SCENE_ROLES = {
    "Gameplay": SceneRole.ACTIVE,
    "BRB": SceneRole.BREAK,
    "Starting Soon": SceneRole.STARTING,
    "Ending": SceneRole.ENDING,
}


def test_derivation_priority():
    engine = PhaseEngine(SCENE_ROLES, speech_gap_ms=1000.0)

    # No OBS state yet -> UNKNOWN.
    assert engine.current_phase(now=0.0) == Phase.UNKNOWN

    # OBS scene is authoritative: BRB -> BREAK, regardless of speech state.
    engine.on_obs_state("BRB")
    assert engine.current_phase(now=1.0) == Phase.BREAK

    # Active scene with no speech yet this session -> ACTIVE_SPEAKING (assume active).
    engine.on_obs_state("Gameplay")
    assert engine.current_phase(now=2.0) == Phase.ACTIVE_SPEAKING

    # Speech just happened -> still speaking (gap below threshold).
    engine.on_transcript_final(now=2.0)
    assert engine.current_phase(now=2.5) == Phase.ACTIVE_SPEAKING

    # Gap exceeds speech_gap_ms -> refines to ACTIVE_SILENT.
    assert engine.current_phase(now=3.2) == Phase.ACTIVE_SILENT

    # Chat velocity plays no role in phase (advisory-only) — not modeled here
    # at all, so there's nothing to assert beyond its absence from the API.


def test_unknown_is_conservative():
    engine = PhaseEngine(SCENE_ROLES, speech_gap_ms=1000.0)

    # Unmapped scene -> UNKNOWN, not a guess.
    engine.on_obs_state("Some Unmapped Scene")
    assert engine.current_phase(now=0.0) == Phase.UNKNOWN
    assert is_safe_window(Phase.UNKNOWN) is False

    # OBS disconnect -> UNKNOWN even if the last known scene was safe.
    engine.on_obs_state("BRB")
    assert engine.current_phase(now=1.0) == Phase.BREAK
    engine.on_obs_disconnected()
    assert engine.current_phase(now=2.0) == Phase.UNKNOWN


def test_safe_windows():
    assert is_safe_window(Phase.ACTIVE_SILENT) is True
    assert is_safe_window(Phase.BREAK) is True
    assert is_safe_window(Phase.STARTING) is True
    assert is_safe_window(Phase.ACTIVE_SPEAKING) is False
    assert is_safe_window(Phase.ENDING) is False
    assert is_safe_window(Phase.UNKNOWN) is False
