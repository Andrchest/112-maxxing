"""`TurnDetector` over synthetic audio (HLD `50-voice-pipeline.md` §4; SPEC §17, §18).

Every case here is one row of §4.4's transition table or one clause of its finalization
paragraph, driven through the real `EnergyVAD` so that the thresholds under test are the
thresholds a running process would apply.
"""

from __future__ import annotations

import pytest
from app.application.voice.config import VoiceTurnConfig
from app.application.voice.turn_detector import TurnDetector, TurnDetectorState, TurnEndReason

from tests.unit.application.voice.conftest import concat, drive, make_vad, quiet, speech


async def test_pre_roll_is_kept_so_the_turn_starts_before_the_vad_trigger(
    config: VoiceTurnConfig,
) -> None:
    """§4.2: the recognised audio begins `pre_roll_ms` before the trigger, not at it."""
    frames = concat(
        quiet(config, 500, 0),
        speech(config, 1000, 0),
        quiet(config, 800, 0),
    )
    detector = TurnDetector(config)
    steps = await drive(detector, make_vad(config), frames)

    started = [step.started for step in steps if step.started is not None]
    finished = [step.finished for step in steps if step.finished is not None]
    assert len(started) == 1
    assert len(finished) == 1
    turn = finished[0]

    onset_ms = started[0].start_ms + config.pre_roll_ms
    # The audio really starts before the onset: at least the configured pre-roll, and at most one
    # analysis frame more (the buffer holds `ceil(pre_roll_ms / vad_frame_ms)` whole frames).
    audio_ms = len(turn.audio) * 1000 // (config.sample_rate * 2)
    speech_ms = audio_ms - config.pre_roll_ms
    assert speech_ms > 0
    assert turn.start_ms == max(0, onset_ms - config.pre_roll_ms)
    assert turn.end_ms == turn.start_ms + audio_ms


@pytest.mark.parametrize("endpoint_silence_ms", [250, 300, 350])
@pytest.mark.parametrize("speech_start_threshold", [0.55, 0.80])
async def test_endpoint_fires_at_the_configured_silence(
    endpoint_silence_ms: int, speech_start_threshold: float
) -> None:
    """SPEC §17: the endpoint is configuration, not a literal in the detector.

    Sweeping `endpoint_silence_ms` (and, separately, the start threshold, so the test also proves
    the *other* end of the machine is read from the config) is what makes hard-coding 300 in
    `turn_detector.py` a failing test rather than an invisible regression.
    """
    config = VoiceTurnConfig(
        endpoint_silence_ms=endpoint_silence_ms,
        speech_start_threshold=speech_start_threshold,
    )
    frames = concat(
        quiet(config, 500, 0),
        speech(config, 1000, 0),
        quiet(config, 2000, 0),
    )
    detector = TurnDetector(config)
    vad = make_vad(config)

    silence_frames_seen = 0
    fired_after = None
    in_turn = False
    for frame in frames:
        result = await vad.process(frame)
        step = detector.process(frame, result, playback_active=False)
        if step.started is not None:
            in_turn = True
        if in_turn and result.speech_probability < config.speech_end_threshold:
            silence_frames_seen += 1
        if step.finished is not None:
            fired_after = silence_frames_seen
            break

    expected_frames = -(-config.endpoint_silence_ms // config.vad_frame_ms)
    assert fired_after == expected_frames, (
        f"endpoint fired after {fired_after} silent frames, expected {expected_frames} "
        f"for endpoint_silence_ms={config.endpoint_silence_ms}"
    )


async def test_sub_min_turn_is_discarded_but_both_boundaries_are_reported(
    config: VoiceTurnConfig,
) -> None:
    """§4.4: below `min_turn_ms` there is no ASR and no response — but the pair is still logged."""
    short = VoiceTurnConfig(min_turn_ms=1500)
    frames = concat(
        quiet(short, 500, 0),
        speech(short, 400, 0),
        quiet(short, 800, 0),
    )
    detector = TurnDetector(short)
    steps = await drive(detector, make_vad(short), frames)

    assert [step.started is not None for step in steps].count(True) == 1
    finished = next(step.finished for step in steps if step.finished is not None)
    assert finished.discarded_short is True
    assert finished.end_reason is TurnEndReason.ENDPOINT_SILENCE
    # A turn that is long enough, with the same audio, is not discarded — so the flag is about
    # `min_turn_ms` and not about something else in the fixture.
    generous = short.model_copy(update={"min_turn_ms": 100})
    detector = TurnDetector(generous)
    steps = await drive(detector, make_vad(generous), frames)
    finished = next(step.finished for step in steps if step.finished is not None)
    assert finished.discarded_short is False


async def test_max_turn_ms_finalizes_a_turn_that_never_stops(config: VoiceTurnConfig) -> None:
    """§4.4: `turn_ms >= max_turn_ms` forces `end_reason = MAX_TURN_MS`."""
    capped = VoiceTurnConfig(max_turn_ms=5000)
    frames = concat(quiet(capped, 200, 0), speech(capped, 8000, 0))
    detector = TurnDetector(capped)
    steps = await drive(detector, make_vad(capped), frames)

    finished = next(step.finished for step in steps if step.finished is not None)
    assert finished.end_reason is TurnEndReason.MAX_TURN_MS
    assert finished.duration_ms >= capped.max_turn_ms


async def test_endpointing_returns_to_in_speech_when_speech_resumes(
    config: VoiceTurnConfig,
) -> None:
    """§4.4: ENDPOINTING + speech → IN_SPEECH; a pause mid-sentence is one turn, not two."""
    pause_ms = config.endpoint_silence_ms // 2
    frames = concat(
        quiet(config, 300, 0),
        speech(config, 500, 0),
        quiet(config, pause_ms, 0),
        speech(config, 500, 0),
        quiet(config, 1000, 0),
    )
    detector = TurnDetector(config)
    steps = await drive(detector, make_vad(config), frames)

    assert [step.started is not None for step in steps].count(True) == 1
    finished = [step.finished for step in steps if step.finished is not None]
    assert len(finished) == 1
    assert detector.state is TurnDetectorState.IDLE


async def test_transport_close_finalizes_an_open_turn(config: VoiceTurnConfig) -> None:
    """§4.4's last row: "any | transport closed | IDLE | finalize with TRANSPORT_CLOSED"."""
    frames = concat(quiet(config, 300, 0), speech(config, 900, 0))
    detector = TurnDetector(config)
    steps = await drive(detector, make_vad(config), frames)
    assert not [step for step in steps if step.finished is not None]
    assert detector.turn_open is True

    closed = detector.close()
    assert closed.finished is not None
    assert closed.finished.end_reason is TurnEndReason.TRANSPORT_CLOSED
    assert detector.state is TurnDetectorState.IDLE
    # Closing again is a no-op: there is no turn left to finalize twice.
    assert detector.close().finished is None


async def test_barge_in_uses_the_shorter_sustain_while_playback_is_active() -> None:
    """§4.3/§6.1: during playback the sustain threshold is `barge_in_min_speech_ms`.

    The two runs differ only in `playback_active`, and the burst is long enough for the barge-in
    sustain but too short for the cold-start one — so a detector that ignored the flag would open
    no turn at all in the second run.
    """
    config = VoiceTurnConfig(barge_in_min_speech_ms=64, speech_start_min_ms=384)
    burst_ms = 160
    frames = concat(quiet(config, 300, 0), speech(config, burst_ms, 0), quiet(config, 1000, 0))

    cold = TurnDetector(config)
    cold_steps = await drive(cold, make_vad(config), frames, playback_active=False)
    assert not [step for step in cold_steps if step.started is not None]

    hot = TurnDetector(config)
    hot_steps = await drive(hot, make_vad(config), frames, playback_active=True)
    started = next(step.started for step in hot_steps if step.started is not None)
    assert started.was_during_playback is True
    finished = next(step.finished for step in hot_steps if step.finished is not None)
    assert finished.is_barge_in is True
