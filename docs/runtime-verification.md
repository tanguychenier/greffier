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
assets fail the check. The macOS bundle also processes the synthetic reference with the actual
whisper.cpp and speaker models before its ZIP is accepted. Word edits, the
speaker sequence and reference facts must pass. Local model trials still
measure scenarios beyond this reference.

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

If the native transcription stalls, add `--field whisper_diagnostic=true`
to that dispatch. This records bounded direct whisper.cpp trials on CPU with
and without VAD. After captured VAD stacks stalled at OpenMP barriers, the
current probe tests a single worker with the speech detector retained. A stalled diagnostic process
is sampled before it is stopped. The synthesis process exits before the trial
so its voice model and worker pools cannot compete for CPU time. A diagnostic
run collects evidence only and does not validate the complete meeting pipeline.

## Hardware checks

A runner or Wine cannot validate the complete audio setup of another computer.
Microphone capture, system audio, device selection, long recordings, native
permissions, Gatekeeper and GPU drivers still need checks on the intended
hardware. In particular, macOS CoreAudio permissions and Metal, and Windows
capture devices and loopback audio, require a native hardware trial.

The Windows recording adapter currently uses FFmpeg DirectShow. A named audio
input must be available to FFmpeg. The presence of WASAPI in Windows does not
establish that this adapter can capture system audio automatically.

The meeting composition does not automatically activate whisper.cpp's external
GGML speech detector. Native tests of version 1.9.2 stalled at its OpenMP
barriers, and that version initializes its detector with four internal workers
independently of the CLI thread option. Whisper's own no-speech filtering stays
active, as in live and dictation mode. Entirely silent recordings are rejected
by the pipeline before the transcriber starts. Native CPU threads follow the
available CPU count, and child-only worker defaults avoid nested pool contention
while preserving explicit environment settings.


The Windows executable and Linux AppImage also process the reference meeting before release packaging. The frozen executable must match its native runtime report, reject digital silence, recover both speakers in the five expected turns and preserve five checked facts with at most five percent word edits. Fixture synthesis exits before processing. These checks use CPU models and do not record a microphone or invoke a writer. The reports are retained as meeting-windows-release and meeting-linux-release.

Reference synthesis varies between generations. Proof artifacts retain the exact recording, its digest and timeline for replay, including when a package fails a critical fact. A lower-noise synthesis experiment worsened word accuracy and speaker identification and was not adopted. Successful checks on a reference recording do not guarantee correct transcription of other recordings.

All native release pipelines now replay the same versioned reference in `tools/fixtures/reference-meeting`. It is the first retained Linux recording from run 38375465940, generated with the normal two-voice VITS settings. Its manifest verifies both the audio and exact timeline before processing. Fixing the input makes comparisons reproducible across systems; the previously observed facturation/fabrication and mercredi/matredi errors remain known limits on other recordings.
