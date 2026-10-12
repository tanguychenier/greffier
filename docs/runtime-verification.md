# Runtime verification

Run checks against the installed application as well as its source tree.

## Automated checks

The release workflow opens the packaged application on native macOS and Windows
runners and the AppImage on Linux under Xvfb. It visits all seven tabs at widths
of 880 and 1280 pixels, checks that pages map and buttons fit horizontally, and
records callback errors. A failed or incomplete report blocks the distribution.
The runtime JSON files are retained as workflow artifacts.

The proof captures no pixels and inspects only the window it creates. It closes
that window when the checks finish. Widget geometry cannot establish visual
quality or validate every interaction.

The frozen Windows and Linux launchers also run `--check-audio` before their
archives are attached. This decodes a synthetic WAV with faster-whisper and
runs its bundled Silero speech detector. It needs no downloaded transcription
weights, microphone or window. Incompatible decoder APIs and missing ONNX
assets fail the check. Full transcription still needs a separate model trial.

For a separate test installation, run the same protocol locally.

```sh
python tools/check_runtime.py --output runtime.json -- ./Greffier-x86_64.AppImage
python tools/check_runtime.py --output runtime.json -- ./dist/Greffier/Greffier.exe
python tools/check_runtime.py --output runtime.json -- /path/to/Greffier.app/Contents/MacOS/Greffier
```

On Linux without FUSE, set `APPIMAGE_EXTRACT_AND_RUN=1`. On a headless Linux
host, run the command under `xvfb-run -a`. On Windows, Python is needed only for
the checking script, not for the packaged application. The script uses temporary
settings on Linux and Windows. On macOS, use a test account because native
platform directories are independent of XDG settings.

## Audio and writing

Integration tests use synthesised audio and installed models. Run them
sequentially when several models share a small graphics card.

```sh
pytest -m integration tests/integration/test_whole_chain.py tests/integration/test_slice_segmenter.py
pytest -m integration tests/integration/test_replay_e2e.py
pytest -m integration tests/integration/test_live_with_assistant.py
pytest -m integration tests/integration/test_bank_across_meetings.py
GREFFIER_TEST_OLLAMA_MODEL=installed-model pytest -m integration tests/integration/test_ollama_minutes.py
```

Missing models are reported as skips. A skip is not successful execution of the
scenario. The local Ollama regression accepts either a faithful table or an
explicit refusal, and does not hide transport failures. It needs no remote
account and sends no minutes.

The local writer checks attributed French and English Markdown minutes for
unsupported participants, asserted roles and some collective actions assigned
to a person. It requests one correction and refuses a response that still
fails. The meeting pipeline preserves audio and the transcript and sends
nothing after a writer failure. These checks do not prove every paragraph is
factually correct. Conversation mode, custom instructions and other output
languages retain their existing behavior.

## Published macOS meeting check

The release workflow has an optional `meeting_proof` dispatch that verifies
an already published macOS ZIP against its GitHub SHA256, then runs its own
interpreter through a synthetic meeting with the actual whisper.cpp and
speaker models. It downloads the models into the runner's temporary folder,
disables writing and sending, and retains a report and the synthetic transcript.

```sh
gh workflow run release.yml --field meeting_proof=true --field release_tag=v0.3.30
```

The check compares the output with the words used to generate the audio,
normalizing punctuation, case and the spelling of preproduction. It requires
at most five percent word edits, the five expected speaker turns in order,
and the stated number of anomalies and scheduling facts. The two VITS timbres
make the same reference available on every platform. A passed synthetic trial
is not a measure of accuracy on all meetings. This dispatch does not build,
replace or publish any release assets.

## Hardware checks

A runner or Wine cannot validate the complete audio setup of another computer.
Microphone capture, system audio, device selection, long recordings, native
permissions, Gatekeeper and GPU drivers still need checks on the intended
hardware. In particular, macOS CoreAudio permissions and Metal, and Windows
capture devices and loopback audio, require a native hardware trial.

The Windows recording adapter currently uses FFmpeg DirectShow. A named audio
input must be available to FFmpeg. The presence of WASAPI in Windows does not
establish that this adapter can capture system audio automatically.
