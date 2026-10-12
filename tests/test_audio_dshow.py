"""Windows inputs must come from audio devices rather than a fictitious default."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from greffier.adapters import audio_dshow, audio_ffmpeg, dictation_ffmpeg, system_diagnostic


@pytest.fixture
def listed(monkeypatch):
    output = ('[dshow @ abc] "Webcam" (video)\n'
              '[dshow @ abc] "Microphone (USB)" (audio)\n'
              '[dshow @ abc] Alternative name "@device_cm_{audio}"\n')
    monkeypatch.setattr(audio_dshow.subprocess, "run", lambda *_a, **_kw:
                        SimpleNamespace(stderr=output, returncode=1))


@pytest.mark.usefixtures("listed")
def test_video_and_alternative_names_do_not_become_microphones():
    assert audio_dshow.devices() == ("Microphone (USB)",)


@pytest.mark.usefixtures("listed")
@pytest.mark.parametrize("configured", ["", "default"])
def test_an_unambiguous_input_replaces_the_fictitious_default(configured):
    assert audio_dshow.input_name(configured) == "Microphone (USB)"


def test_a_configured_name_is_not_changed_or_probed(monkeypatch):
    monkeypatch.setattr(audio_dshow, "devices", lambda: pytest.fail("unexpected probe"))
    assert audio_dshow.input_name("CABLE Output") == "CABLE Output"


@pytest.mark.parametrize("inputs", [(), ("USB", "Built-in"), ("USB", "USB")])
def test_absent_or_ambiguous_inputs_are_refused(monkeypatch, inputs):
    monkeypatch.setattr(audio_dshow, "devices", lambda: inputs)
    with pytest.raises(RuntimeError):
        audio_dshow.input_name("default")


@pytest.mark.parametrize("trouble", [FileNotFoundError(), subprocess.TimeoutExpired("ffmpeg", 15)])
def test_a_failed_probe_does_not_invent_an_input(monkeypatch, trouble):
    def fail(*_args, **_kwargs):
        raise trouble
    monkeypatch.setattr(audio_dshow.subprocess, "run", fail)
    assert audio_dshow.devices() == ()


@pytest.mark.usefixtures("listed")
def test_recording_and_dictation_use_the_same_real_input(monkeypatch):
    monkeypatch.setattr(audio_ffmpeg, "SYSTEM", "Windows")
    monkeypatch.setattr(dictation_ffmpeg, "SYSTEM", "Windows")
    expected = ["-f", "dshow", "-i", "audio=Microphone (USB)"]
    assert audio_ffmpeg.FfmpegRecorder("default")._input() == expected
    assert dictation_ffmpeg._input("") == expected


@pytest.mark.parametrize("inputs", [(), ("USB",)])
def test_the_microphone_diagnostic_uses_detected_inputs(monkeypatch, inputs):
    monkeypatch.setattr(system_diagnostic, "SYSTEM", "Windows")
    monkeypatch.setattr(audio_dshow, "devices", lambda: inputs)
    assert system_diagnostic.mic_present().present == bool(inputs)


def test_native_wasapi_is_not_claimed_as_a_verified_directshow_loopback(monkeypatch):
    monkeypatch.setattr(system_diagnostic, "SYSTEM", "Windows")
    reading = system_diagnostic.system_capture()
    assert not reading.present
    assert not reading.is_blocking
    assert "DirectShow" in reading.remedy
