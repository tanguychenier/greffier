# Greffier

Records a meeting, works out who is speaking, and writes the minutes.
Transcription and voice recognition run **locally**, on macOS, Linux and
Windows — on the graphics card where there is one, on the processor otherwise.
Only the writing of the minutes can leave the machine, and only if you want it
to: `ollama` keeps that here as well.

> A *greffier* is a court clerk: he attends the session, notes who said what,
> and produces the record.

**Greffier speaks French.** The window, the command names and the minutes are
in French, and the name attribution recognises French turns of phrase — `moi
c'est Sandy`, `merci Jacques`, `Jacques, tu peux…`. The transcription language
is a setting and whisper handles a hundred of them, but nothing will pick names
out of an English meeting.

![Greffier's chain: record, transcribe, separate the voices, name them, write, send](assets/chaine.svg)

## What it does

```
meeting audio → transcription → who speaks → names → minutes → mail
```

- **Recording** on two separate channels (your microphone on the left, everyone
  else on the right): in a video call, telling your voice from the others' is a
  hardware certainty, not a deduction.
- **Transcription** by the `large-v3` model: whisper.cpp with Metal
  acceleration on macOS, faster-whisper elsewhere — on the NVIDIA card if it is
  there, on the processor otherwise.
- **Voice identification** by voice print (pyannote + TitaNet), locally.
- **Name attribution**: participants name each other during the meeting, and
  the tool collects those clues and cross-checks them. Nobody has to introduce
  themselves. What stays uncertain is proposed, never asserted.
- **Live transcription, correctable**: what is being said appears in the window
  during the meeting, with who is speaking. Clicking a name corrects it — and
  that correction covers every passage of that voice, goes into the voice bank,
  and carries into the final minutes. Until then, a wrong attribution was only
  caught by re-reading the minutes, an hour too late.
- **Voice bank**: once a voice carries a name, the person is recognised at
  later meetings.
- **Minutes** with timestamps, speaking time and decisions.

## Installation

One command, on all three systems:

```sh
git clone https://github.com/tanguychenier/greffier.git
cd greffier
python3 outils/installer.py          # Windows: python outils\installer.py
```

The installer **finds what is missing and installs it**, rather than printing a
list of commands to copy out. It asks before each installation, it is **safe to
re-run**, and it picks up models already on the machine instead of downloading
them again.

On macOS it also builds **`/Applications/Greffier.app`**, a self-contained
application: interpreter, libraries and code are copied inside, and nothing
points back at the clone or at a hidden folder in the account. It is signed
with a **stable** identity — an Apple certificate already in the keychain if
there is one, otherwise a local certificate created once and for all, macOS
then asking for the login password a single time — so that granted permissions
survive reinstallation. A code change only shows up there by re-running the
installer; the command line in the clone follows the code.

It then moves on to the **configuration assistant**, which asks the questions
that matter and writes a valid `.env`:

- what the machine can do — memory, compute, microphone, system sound capture —
  and **which model it can run without suffering**;
- who writes: is the command-line assistant installed, and **is the session
  open**? Without that, the failure would only surface after an hour of
  transcription;
- where the minutes arrive: by mail — Outlook already authenticated, otherwise
  SMTP, with the password kept out of the file — or simply in a folder;
- the vocabulary of your meetings, which also serves as a list of words never
  to mistake for first names.

```sh
greffier configurer      # re-runnable when the machine or the address changes
greffier diagnostic      # report without changing anything
```

```
python3 outils/installer.py --verifier   # report without installing anything
python3 outils/installer.py --oui        # without asking
```

It uses nothing but the Python standard library: it has to run *before*
anything is installed, so it cannot depend on anything. Python 3.9 is enough to
start it.

### What it does, and what differs per system

| | macOS | Linux | Windows |
|---|---|---|---|
| Transcription | whisper.cpp, Metal-accelerated | faster-whisper | faster-whisper |
| Voice prints | sherpa-onnx | sherpa-onnx | sherpa-onnx |
| Capturing everyone else's sound | BlackHole (driver to install) | PipeWire/PulseAudio monitor, **nothing to install** | WASAPI loopback, built in |
| Writing the minutes | Ollama (local) or a command-line assistant | same | same |
| Sending the minutes | Outlook already authenticated, otherwise SMTP | SMTP | SMTP |
| Interface | **the same window** (Tkinter) | same, but without font antialiasing | same |

On Linux the window renders without font antialiasing: the Tk carried by the
interpreter `uv` installs is built without Xft (`tk::pkgconfig get fontsystem`
returns `x11`), so it only exposes the historical X11 families. Apt's has one
(`xft`), but Greffier requires Python 3.13, which Ubuntu 24.04 does not ship.
The text is legible and in the right place; it is not crisp.

The core — transcription, voice identification, name attribution, minutes —
runs identically everywhere. What differs is **system sound capture** and **the
interface**, precisely the two places the architecture isolates behind ports.

On macOS two audio devices have to be created once: `Reunion Entree`
(aggregate: microphone + BlackHole) and `Reunion Sortie` (multi-output:
headphones + BlackHole). On Linux and Windows there is nothing of the sort — the
system already exposes a way to re-record its own output.

> A macOS aggregate device references **specific hardware**. Headphones
> unplugged means the microphone is missing from the aggregate, which means a
> silent recording. It has to be rebuilt when the hardware changes.

### The models

Downloaded once, no network call afterwards.

| Model | Role | Size | When |
|---|---|---|---|
| `ggml-large-v3-turbo` | transcription | 1.5 GB | macOS only |
| `ggml-small` | live transcription | 0.5 GB | macOS, optional |
| `ggml-silero-v5.1.2` | speech detection | 0.9 MB | macOS only |
| `faster-whisper large-v3` | transcription | 1.5 GB | Linux and Windows |
| `nemo_en_titanet_large` | voice prints | 98 MB | everywhere |
| `pyannote-segmentation-3.0` | splitting into speaking turns | 6 MB | everywhere |

On Linux, an NVIDIA card is not enough on its own: CTranslate2 wants cuBLAS and
cuDNN, which no distribution ships with the driver. The installer offers the
`cuda` extra where it can serve. It is worth taking — `large-v3` in `int8`
needs eight minutes for thirty-eight seconds of audio on the processor, and
twelve seconds on the card.

### Writing the minutes

**A command-line assistant by default.** Telling a decision from a hypothesis,
attaching a position to a person, flagging what the transcription lost rather
than filling it in: that is out of reach of models that run on a laptop. It is
the **only link in the chain that leaves the machine** — the transcription goes
to a remote API — and it is a deliberate choice.

To let nothing out at all, **Ollama** replaces it without changing anything
else, at the price of a coarser summary:

```sh
GREFFIER_COMPTE_RENDU__MOTEUR=ollama greffier traiter reunion.wav
```

The assistant writes with the **second model in the range**, not the first. That
is a choice, not a limitation put up with: writing from a transcription that is
already split and attributed is summarising work, not long reasoning. The top of
the range produces the same document while eating through a quota far faster —
one meeting a day is enough to feel it. The model is requested **explicitly** at
call time, so that the minutes do not change author according to the machine's
personal setting. It can be changed in the Settings tab, or through
`GREFFIER_COMPTE_RENDU__MODELE`.

With neither one nor the other, transcription and voice identification still
work; only the minutes are missing.

### Configuration

Through environment variables, a `.env` file, or a `config.toml`. In that order
of precedence: it must be possible to force a setting for the length of one
command without editing a file.

```sh
cp .env.exemple .env        # at the root, or in the configuration folder
```

| System | Configuration and data |
|---|---|
| macOS | `~/Library/Application Support/Greffier` — the native location, not a hidden folder: the machine's guards challenged every access to `~/.config` and `~/.local`, to the point of refusing a write in the middle of a meeting |
| Linux | `~/.config/greffier` and `~/.local/share/greffier` |
| Windows | `%APPDATA%\greffier` and `%LOCALAPPDATA%\greffier` |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME`, when set, win everywhere. A machine
installed before that change is moved by the installer, losing nothing.

The common settings live **in the window**, Settings tab: microphone, writer's
account, transcription model and language, writer and its model, recipient, live
transcription, light or dark appearance. **No button to confirm**: every change
applies and is written to `config.toml` at once, the previous version staying in
`config.toml.precedent`. The theme repaints the window on the spot, without a
restart.

One block says what writes: installed version, address and organisation of the
connected account, plan. Three actions beside it — sign in, which opens a
terminal where signing in actually happens; update; refresh. Without a session
everything works except the minutes, and the failure would only surface after
the transcription. Domain vocabulary and the words that are never first names
stay in the file: they are lists, and a form would truncate them.

| Variable | Role |
|---|---|
| `GREFFIER_COMPTE_RENDU__MOTEUR` | `claude`, `ollama` or `aucun` |
| `GREFFIER_COMPTE_RENDU__MODELE` | the writer's model — the second of the range by default |
| `GREFFIER_COMPTE_RENDU__DESTINATAIRE` | who to send the minutes to |
| `GREFFIER_TRANSCRIPTION__LANGUE` | two-letter code; **left empty, the model works it out itself** |
| `GREFFIER_TRANSCRIPTION__VOCABULAIRE` | proper nouns from the context — the setting that most improves the transcription of rare terms |
| `GREFFIER_LOCUTEURS__PAS_DES_PRENOMS` | words never to mistake for first names |
| `GREFFIER_LOCUTEURS__PERSONNES` | how many people are in the room, when you know — without it the clustering over-splits |
| `GREFFIER_DIRECT__ACTIF` | `false` turns off live transcription, and its compute cost |
| `GREFFIER_DIRECT__PERIODE` | seconds between two transcribed slices (10 by default) |
| `GREFFIER_APPARENCE__THEME` | `systeme`, `clair` or `sombre` |

The double underscore separates the section from the field. None of this lives
in the repository: mail address, domain vocabulary and project names belong to
each person.

### macOS permissions

Asked **once**, on first use, as for any application. The package signature
being stable, neither an update nor a reinstallation asks again.

- **Microphone** — without it, the recording is silent.
- **Automation ▸ Microsoft Outlook** — only for sending mail. The system dialog
  does not always appear, the processing running detached:
  `System Settings ▸ Privacy & Security ▸ Automation`.

## Does it actually work?

These are not claims: every line below has been run.

**Clean-room installation, macOS** — fresh clone, no model present, resumption
disabled. The 1.5 GB were really downloaded (no symbolic link in the model
folder), the tests passed, voice print model loaded.

**Installation on Linux, bare image** — reproducible by you:

```sh
mkdir contexte && cp -r . contexte/greffier
docker build -f outils/preuve-linux.Dockerfile -t greffier-preuve contexte
```

From a `python:3.13-slim` with nothing but git, the installer puts ffmpeg in
place through apt, falls back to faster-whisper for want of whisper.cpp,
downloads the models, falls back to `venv + pip` for want of `uv`, prepares the
transcription model, writes the configuration — then the tests pass and a
192-dimension voice print is really extracted under Linux.

**Then on a real Linux desktop**, which the container could not show: the
installer goes all the way through, the window opens, and the chain runs on real
recordings. Four defects came out of it, all fixed, and they are written up in
[`docs/reste-a-faire.md`](docs/reste-a-faire.md).

**The live thread, replayed in real time** — a synthetic three-channel video
call is rewritten by ffmpeg at the speed of sound, which reproduces capture
exactly, indeterminate-size header included. The real command runs on it.
Result: the person at the microphone shown as "Toi" by the channel, the three
remote turns grouped into a single voice, a correction entered during the
meeting propagated to the following sentences **and paid into the voice bank**,
from which the final minutes pick it up.

Measured cost of a ten-second slice, end to end, on an Apple Silicon Mac:
**1.50 s** — splitting 0.04, channel levelling 0.53, transcription 0.89, voice
print 0.04. With the *large* model, for want of the small one: the ten-second
period holds with six times the margin needed.

**Real chain, end to end** — an integration test **synthesises a fake
two-voice meeting** (a real meeting contains working exchanges and identifiable
voices, so it cannot serve as a test fixture), runs it through whisper and
diarisation, and checks that both first names — spoken as self-introduction, as
address and as thanks — are found:

```sh
pytest -m integration
```

It is what found a defect invisible to the unit tests: whisper starts its first
line at `00:00,00` while the segmentation only detects speech at `00:00,30`, so
a self-introduction fell between two speaking turns and designated nobody.

**On real voices** — two public French interviews and a real four-person
meeting, since synthetic voices never talk over each other and never move away
from the microphone. Both interviews come out with the right two voices. On
[ES2002a of the AMI corpus](https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/) —
four people, one mixed channel, four headset tracks as an unarguable reference —
four people come out as six. The transcription holds; the clustering
over-splits. Numbers in [`docs/reste-a-faire.md`](docs/reste-a-faire.md).

**Quality gate** — `ruff`, `mypy` and the tests, all three blocking, replayed by
`.github/workflows/ci.yml` on every push and every pull request. The full Linux
installation proof downloads the models, so it stays on manual dispatch.

## Use

```sh
greffier enregistrer "point recette"   # starts
greffier statut                        # where we are
greffier arreter                       # stops, transcribes, identifies, writes

greffier reunions                      # what has already been processed
greffier voix                          # the voices of the last meeting
greffier voix --ecouter 3              # pull ten seconds out of it
greffier voix --nommer 3 --nom Josiane # name it: recognised from then on
greffier connus                        # the voices already in the bank

greffier assister                      # shows what is said, collects proposals
greffier propositions                  # links, instructions and decisions collected

greffier montage                       # the notable passages, real voices
greffier lire                          # the minutes read aloud
greffier tickets                       # the decided actions, ready to open
greffier archiver                      # compresses processed recordings
```

### The window

![The five views of the window: Meetings, Live, Voices, Conversation, Settings](assets/vues.svg)

```sh
greffier fenetre        # or double-click Greffier in the Launchpad
```

Everything can be done there without a terminal, and **the same on all three
systems**: Tkinter comes with Python, there is nothing to install.

![Greffier's window: a breathing recording dot and two live level meters](assets/demo.gif)

- **Start, pause, finish.** The pause earns its keep: an interruption must not
  force the session closed, or the processing starts and a second meeting has to
  be held, with two sets of minutes at the end.
- **`Toi` / `Les autres` level meters**, to check that the microphone is picking
  up *before* the meeting rather than an hour too late, and who is speaking
  right now. Provenance is enough to say: the microphone on one side, the system
  loopback on the other.
- **`En direct` tab**: what is being said, as it comes, with who is speaking.
  The tab opens by itself when the meeting starts.
  - `Toi` comes from the **channel**: the microphone designates the person
    recording, without consulting any model, and without ever being wrong.
  - A name followed by a **`?`** comes from the voice print: it is a proposal,
    not an assertion.
  - **Clicking the name corrects it.** By default the correction covers the
    whole voice — when the tool gets the person wrong, it gets them wrong for
    every passage; "only this sentence" is there for overlaps. The correction
    shows at once, applies to the following sentences, goes into the voice bank,
    and that is how the final minutes find the person on their own.
- **The machine sets itself up**: microphone actually plugged in, system output
  switched to the capture loopback, gain raised if it is too low. Those three
  settings had to be done by hand during a real meeting, and their absence cost
  the voice of the person recording.
- **Naming voices**, by listening to ten seconds. A named voice goes into the
  bank and recognises itself afterwards.
- **Asking a question** about a set of minutes, and sending it by mail.

There is **no subject to type in**: the minutes give the meeting its title,
written after listening to it. Asking beforehand would assume you know what a
meeting is going to be about.

## Architecture

Hexagonal — the domain at the centre, the techniques around it.

```
src/greffier/
├── domaine/       business core, no dependency: models, name attribution rules,
│                  voice print matching. Testable without audio.
├── ports/         interfaces the domain expects (Protocol)
├── application/   use cases: orchestration of the ports
├── adaptateurs/   ffmpeg, whisper.cpp, sherpa-onnx, AI writer, Outlook, CoreAudio
├── interface/     the window (Tkinter): palette, drawn shapes, screens
└── cli.py         command-line interface (Typer)
macos/             audio device creation (Swift) and the .app bundle
```

The domain knows nothing of whisper, ffmpeg or Outlook. That is what makes it
possible to test the name attribution rules on hand-written sentences, in a few
milliseconds, without a 1.6 GB model.

## Distributing

```sh
uv build --wheel                     # produces dist/greffier-0.1.0-py3-none-any.whl
pipx install dist/greffier-*.whl     # or pip install, in a dedicated environment
```

The wheel holds the code only: the models are fetched on the first run of
`outils/installer.py`.

## Development

The installer already does everything needed. To recalibrate the voice
recognition thresholds on a recording of your own:

```sh
.venv/bin/python outils/calibrer_seuils.py <recording.wav>
.venv/bin/python outils/verifier_fusion.py <recording.wav>
```

The method and the thresholds in force are in
[`docs/calibrage.md`](docs/calibrage.md).

Install the git hooks once and for all:

```sh
./outils/crochets/installer.sh
```

A commit that does not pass `ruff`, `mypy` and the tests is then **refused**.
Running the checks "on the side" is not enough — three quality remarks made it
into commits before that guard existed. `--no-verify` remains possible,
knowingly.

## State

The port from the original chain of scripts (`~/reunions/`, abandoned on
2026-08-24) is finished: the eight batches are done and the whole chain runs end
to end, tried on real meetings, on a synthetic fixture, and on public
recordings. What is still open — a few minor defects, and what has never met
reality (Windows, live in-person) — is detailed in
[`docs/reste-a-faire.md`](docs/reste-a-faire.md).

## Frame

Named voice prints are biometric data within the meaning of Article 9 of the
GDPR. They do not leave the machine, but participants must be told that the
meeting is being recorded and the voices recognised.
