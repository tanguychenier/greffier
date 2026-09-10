# What remains to be done

State as of 2026-09-01, after the fix of the last three defects of the initial
diagnosis (segmentation, lost proposal, live text).

The eight porting batches have been done since 25 August. This document now
lists only one thing: **what usage broke, what was fixed, and what remains
open.** The history of the batches is in `git log`; repeating it here no longer
served any purpose.

## What the first real meeting taught

An hour of discussion, four people. The minutes came out, and they were wrong
on several counts. Every defect below was measured on that recording, not
supposed.

| Defect | What it cost | State |
|---|---|---|
| Mixing the channels before segmentation | **13 min of speech missing** from the minutes, and the document stated that the person had not spoken | fixed |
| The model invented sentences on weak signal | « Merci d'avoir regardé cette vidéo ! » [thank you for watching this video] where the person was saying « Test, test de réunion » [test, meeting test] | fixed |
| A name resting only on being addressed by others became firm | The first name of an absent person attributed to the voice holding 64 % of the speaking time | fixed |
| Every capitalised word was a first-name candidate | « Ouais » [yeah] promoted to a first name, with 13 min of speaking time | fixed |
| The email went out in MacRoman, as raw Markdown | All French minutes arrived as `r√©union` | fixed |
| The send skipped without a word, and the icon displayed « Compte rendu envoyé » [minutes sent] | Nothing had gone out, the interface stated the opposite | fixed |
| The minutes talked about the tool | 31 % of the document on the plumbing, 9 % on the decisions | fixed |
| Hardware changing during the meeting | A headset plugged in along the way and the voice of whoever is recording is lost | fixed |
| Three settings to be made by hand | System output, microphone, gain: without them the system channels stayed silent | fixed |
| Low coverage alerted nobody | 22 % of the audio with no text, passed over in silence | fixed |
| The icon blind during a reprocessing | Fifteen minutes displaying the previous phase | fixed |
| Nothing was displayed during the meeting | A wrong attribution only showed up in the minutes, an hour too late | fixed |
| `greffier assister` targeted the stitched file, which only exists after the stop | It transcribed **nothing**, and nobody noticed since nothing displayed its work | fixed |
| Nothing started `assister` | The command existed, the window started only the hardware watch | fixed |

Detail and measurements in the commit messages, each of which carries the figure
that motivated the change.

## What live taught

The thread shown during the meeting was proven on a synthetic 30 s video call,
three channels, replayed in real time — so through the real command, the real
splitting into slices and the real models. Every defect below was **measured**
there, and fixed.

| Defect | What it cost | State |
|---|---|---|
| The slice transcribed without channel levelling | **One question in six was not transcribed at all** — the one from the person at the microphone, 6 dB below the loopback. The same defect as the original mixing, reproduced in the live thread | fixed |
| De-duplication on the start of the sentence alone | One sentence in six lost: the same one is timestamped 13.60 in one slice and 12.80 in the next | fixed |
| The voice print taken from the whole block | 0.6 s of local voice at the head of a 1.5 s excerpt was enough to make two participants out of the same person, and a correction did not propagate | fixed |
| The video-call verdict recomputed on every slice | On a slice where only the person at the microphone speaks, no loopback dominates: their voice became one more remote participant | fixed |
| The learning threshold at 6 s, with no second chance | A correction entered at the second sentence **never** made it into the bank: it was displayed, then served neither the following meeting nor the minutes | fixed |
| The position tracked on the meeting clock | After a pause, the clock and the audio written to disk diverge by the whole stopped time, and ffmpeg read past the end of the file | fixed |
| The last seconds never read | You finished your sentence in front of a thread that stopped before it | fixed |

## What direct measurement fixed (2026-09-01)

The last three defects from the initial diagnosis, this time measured against the
models actually present rather than merely assumed from the symptoms.

| Defect | What it cost | State |
|---|---|---|
| The raw clustering threshold, never measured (`threshold=0.8`), merged two voices as early as segmentation | On a three-speaker test set, 2 voices found instead of 3, before the domain's re-stitching even came into play | fixed — `threshold=0.45`, measured and documented in `docs/calibrage.md` |
| `fusionner_voix` merged clusters that held too little material | Two small recent groups crossed `SEUIL_FUSION` by statistical accident | fixed — asymmetric material guard, `MATIERE_MINIMALE_FUSION` |
| `voix_a_nommer` discarded any voice under ten seconds, suggestion included | A first name detected in a short answer never showed up — neither in the naming screen nor in the CLI summary | fixed — a short voice that already carries a name or a proposal escapes the filter |
| The live text duplicated the end of a sentence at the boundary between two slices | « dernier. » then « dernier. Sandy, tu peux nous dire… » : the speaker was right, the text was not | fixed — `retirer_repetition`, word-by-word overlap between two slices |

Tests: synthetic cases `trois-voix` and `proposition-breve` replayed through
the real chain (`tests/integration/test_cas_difficiles.py`), and a deterministic
live test through `Veilleur → Suivi.accueillir → Fil`
(`tests/application/test_veiller.py`), with a double on the `Transcripteur`
port only.

## Naming a voice now regenerates the minutes (2026-09-01)

`voix_a_nommer` and the master file were losing nothing, but nothing replayed
the writing: the whole processing run had to be started again — segmentation
and transcription included — for minutes to carry the right names.

`rendre_transcription` left `Traitement` to become a free function in
`application/restituer.py`, next to the header functions it completes:
`ReunionEnregistree` (the master file read back from disk) satisfies the same
`Transcrite` protocol as `Resultat`, with no conversion.
`regenerer_compte_rendu(reunion, redacteur)` replays that step alone.
`evenements_materiel` (what the hardware live watch observed) is now
persisted in the master file, without which regeneration would have made the
minutes less reliable than the original.

Wired in at three places: `greffier voix --nommer`, `--accepter-propositions`,
and the interactive re-run after `greffier traiter`; on the window side, in a
separate thread (the writer may call a remote API), on the pattern already in
place for « traiter » and « envoyer ».

## The window no longer announces itself as "python3" on macOS (2026-09-01)

`Contents/MacOS/Greffier` is now a copy of the venv interpreter, not a script
that calls it — the name shown in the Dock and the menu bar comes from the
executable actually launched, never from `argv[0]`. Moving it out of its venv
made it lose its environment (`@rpath/libpython3.13.dylib` not found,
`import numpy` failing): two settings are enough to give it back, both
computed by `macos/construire.sh` from the interpreter itself, never guessed:

- a symlink `Contents/lib` pointing at `sys.base_prefix` (where the standard
  library and the `.dylib` live, not the venv);
- `PYTHONPATH`, set by `LSEnvironment` in `Info.plist`, pointing at the venv
  packages and `src/`.

macOS launches the bundle executable with no argument: `lanceur_sitecustomize.py`
(loaded automatically by Python's `site` mechanism, through `PYTHONPATH`)
stands in for the `python -m greffier fenetre` that the old script called.
Pitfall measured along the way: a `sys.exit()` escaping from `sitecustomize` —
a module loaded by `site`, not a script — is not treated as a clean exit by
the interpreter, which reports it as a "Fatal Python error";
`os._exit()` avoids the problem.

Verified by actually building and launching the bundle on this Mac: the menu
bar shows "Greffier", confirmed by a screenshot, by `osascript` (process name,
window present) and by the unified system log (every line carries
`Greffier[pid]`, not `python3[pid]`).

## The macOS bundle found neither claude nor ffmpeg (2026-09-01)

Defect found by actually clicking « Demander » (Conversation tab) and
« Écouter » (Voix tab) in the app built above — not by settling for opening
the window. Two errors: « claude » not found in the PATH for the writing step,
`[Errno 2] No such file or directory: 'ffmpeg'` for the audio excerpt, while
both are installed and work on the command line.

Cause: macOS launches a `.app` bundle with a minimal PATH
(`/usr/bin:/bin:...`), not the shell's — neither Homebrew nor `~/.local/bin`
appears in it. First fix applied, insufficient: `construire.sh` put `PATH`
in `LSEnvironment`, next to `PYTHONPATH`. Replayed under real conditions
(relaunched from Launchpad, not just `open` in a terminal): `PYTHONPATH`
reaches the process intact, `PATH` does not — back down to the minimum
(`/usr/bin:/bin:/usr/sbin:/sbin`), observed with `ps eww` on the real process.
`LSEnvironment` is therefore not reliable for `PATH` specifically, for a reason
that remains to be understood (macOS seems to reimpose it afterwards).

Fix adopted: `PATH` is no longer entrusted to `LSEnvironment`, but set in
Python in `lanceur_sitecustomize.py` (`os.environ["PATH"] = ... +
os.environ.get("PATH", "")`) — there, nothing else can overwrite it any more.
`construire.sh` generates that file from a template (`macos/lanceur_sitecustomize.py`
in the repository, a placeholder replaced by the PATH measured on the machine
that builds the bundle — always measured, never guessed, since neither ffmpeg
nor claude has a fixed location from one machine to the next).

Specific to macOS: Linux and Windows have no desktop icon yet,
`greffier fenetre` is launched there from a terminal that already has the real
PATH — nothing to fix on the cross-platform code side.

Verified by actually relaunching the app (Launchpad, not a test shortcut) and
by re-reading the process `PATH` with `ps eww`: it now carries Homebrew and
`~/.local/bin`. Side effect to watch: rebuilding the app several times in a row
during the trials brought back the macOS « éditeur inconnu » [unidentified
developer] warning each time (the ad hoc signature changes with every
rebuild) — a nuisance during a test, unrelated to the defect itself.

## What remains open

### The first sentences can miss the « Toi »

The video-call verdict is read from the gap between channels: as long as nobody
else has spoken, there is nothing to compare, and the first speaking turn can be
shown as a voice to name rather than « Toi ». Once the verdict is settled it
holds to the end, so this concerns only the very beginning — and one click
corrects it. Re-judging the turns already written down would mean keeping the
slices, which did not look worth the cost.

### The interface remains austere

First pass done on 2026-09-01: the window changed size on every tab switch
(`racine.geometry()` set once and for all corrects it — otherwise `pack`
computed the parent's size from the single displayed child); two lists
(Réunions, Voix) had **no** scrollbar, and with nothing to show one was
missing, the content beyond the first handful of rows stayed out of reach; the
two `Text` widgets that had one used Tk's native scrollbar (grey, square-edged),
outside the palette of the rest of the window. A drawn `Defileur`
(`interface/apparence.py`) replaces both and covers the two lists that had none;
the cards now carry a light shadow (two frames in the same grid cell, offset by
a few pixels, rather than a `Canvas`, which would have broken size propagation
from the content).

Checked by driving the real window from a script (`Onglets.montrer(...)` called
directly, a screenshot after each tab) rather than by simulating blind clicks on
screen coordinates — too fragile, tried first, abandoned.

What remains: Tkinter has a real ceiling (no CSS, no true transparency, one
`Canvas` per non-standard shape) — a rendering on a par with a modern web
interface is not reachable with this toolkit. What was done removes the two
concrete defects reported (resizing, missing or ugly scrollbars); the austerity
that remains beyond them is a matter of taste, to be refined point by point
rather than through endless iteration.

## What is not to be done

- **The `wip` commit will not be rewritten.** Contrary to what the previous
  version of this document said, it is not orphaned: it is an ordinary commit
  in the history of `main`, between `d7b65df` and `78c0bf2`, carrying
  595 lines of the installer. Renaming it would mean rewriting a history that
  several people now clone. A poor message is not worth that.
- **The local daemon (FastAPI) remains ruled out.** The state file is enough,
  and the window reads it as the icon did.
- **Repository visibility stays private.** The four contributors have named
  access as *Developer*; switching to *Internal* is only useful to open reading
  to the whole school.

## What has never been proven

These points work in theory and have not met the real world.

- **A physical connection made mid-meeting.** Adapting to the hardware is
  proven over 35 scenarios and by two simulated resumptions, never by
  unplugging a real headset during a real meeting.
- **Live in a real meeting.** Proven on a synthetic video call replayed in
  real time, and on a single remote voice. The compute cost of an hour with
  four people, and the behaviour when two people actually talk over each
  other, have not met the real world.
- **Live in person**, in a real meeting. The chain itself is now proven on a
  synthesised round-table meeting: see below.

## The in-person case is proven, and it found a defect (2026-09-03)

Everything used so far was a video call, where the channel identifies the person
recording with certainty. Around a table, everyone speaks into the same
microphone: provenance no longer designates anyone. The case is now held by a
replayable proof.

The test file (`outils/fabriquer_reunion.py --presentiel`) is **stereo**, like
what the device returns: three synthetic voices on the microphone, and on the
system loopback the leak measured on the real table meeting, -53 dB instead of
the expected silence. A silent second channel would have made the trial too
easy: that leak is exactly what was making the verdict come out wrongly as a video call.

### What the measurement confirms

| Check | Measured |
|---|---|
| Channel verdict | `en_visio` returns false; leak at -50.5 dB peak for a microphone at -21.7 dB median |
| The microphone serves as the reference for both channels | `distante` false, `systeme` identical to the microphone |
| Passages declared local | **none** — the channel designates nobody, and nobody is labelled `moi` [me] |
| Participants | several voices, never merged into a single one |
| Self-introduction | « moi c'est Jacques » [I'm Jacques] always designates the person speaking |

### The defect: a straddling sentence went to whoever talked most

`_attacher_voix` gave each line to the voice that spoke the most during its
span. Transcription cuts at the sentence, segmentation at the change of speaker:
when a line **straddles** a change, whoever talked most carried off the other's
words. On a video call, `soustraire` caught the case thanks to the channel; in
person, nothing protected against it.

Measured on the table meeting: « Merci Pierre. On garde donc jeudi… » [thanks
Pierre, so we keep Thursday], said by Jacques, attributed to Pierre — the line
covered 9.6 s of Pierre's speaking turn against 6.1 s of Jacques's, that is 0.61
for the leading voice.

Fixed by `domaine/attribution.py`: below a share of 0.80, the line designates
**nobody**. It keeps its text and its timestamp, and it no longer attributes
wrongly — the rule already adopted for a voice bank that contradicts itself.

The threshold is measured, not chosen: over 29 lines from five synthesised
meetings, 26 hold 0.98 or more (24 at exactly 1.00) and the 3 that straddle a
change of speaker hold 0.50, 0.52 and 0.61. Nothing between 0.62 and 0.97; the
threshold sits in the middle of that empty band.

### What the proof does not measure

The quality of the transcription. Synthetic voices return approximate text — the
same line comes out as « L.S. Dominé, Depuis, I.S.W.A. » from one voice to the
next, and the « Rocko » voice is ignored outright by whisper's speech detector.
A test comparing them would measure `say`, not Greffier. The assertions
therefore only cover what does not depend on timbre.

## SMTP sending and the window outside macOS are proven (2026-09-03)

Two promises rested on documentation, not on a run.

### SMTP, against real servers

The code itself said it had "not yet met a real server". A test server stood
up inside the process would have changed nothing: it answers what it was
taught to answer. `tests/integration/test_smtp_vrais_serveurs.py`
**connects** — `smtp.gmail.com` on 465 and on 587, `smtp.office365.com` on
587, the two providers the code comment named.

What is proven, on all three: the connection succeeds (`NOOP` at 250), the
session is encrypted (`ssl.SSLSocket`, TLS version), and the server announces
`AUTH` — so it did see an encrypted client and stands ready to receive a
password. Getting the convention wrong never reaches that point: a bare `SMTP`
on 465, or an `SMTP_SSL` on 587, fails on the first byte.

No password is needed, so nothing is authenticated and nothing is sent:
sending mail to a third party from a test suite is not a proof, it is one mail
too many.

For that to be possible, `ExpediteurSmtp` exposes two seams:
`message()` composes the mail without opening anything — so what a recipient
receives can be checked **without a network** (`tests/test_courriel_smtp.py`:
accented subject kept whole, both versions of the body, attachment, UTF-8
text) — and `session()` opens the connection. `envoyer()` is now no more than
the assembly of the two.

One defect fixed along the way: the session was only complete at the moment of
sending. RFC 3207 requires greeting again after STARTTLS, the capabilities
announced in the clear no longer holding; `smtplib` does it on demand,
`session()` now does it on opening, `AUTH` included.

### The window opens under Linux

`outils/preuve-fenetre-linux.Dockerfile` builds a bare Debian trixie image,
puts `python3-tk` on it — the interface's only system dependency, exactly the
README line — and opens the real window under `xvfb`. Measured: **Tk 8.6 /
Tcl 8.6**, an 880x660 window, **five tabs painted, no exception raised**.

Debian rather than the `python:3.13-slim` image: the latter compiles its
interpreter without Tk, and Debian's `python3-tk` addresses Debian's python.
No model is downloaded — opening the window asks for none — so the image
builds in a few minutes, where the installation proof takes ten.

### The defect found along the way: the window would not open from the repository

`.venv/bin/greffier` failed on "This probably means that Tcl wasn't
installed properly". The interpreter uv distributes carries the path of the
machine that compiled it: Tk was looking for `init.tcl` in
`/tools/deps/lib/tcl9.0`, which exists on no machine, while Tcl is there, next
to the interpreter. The macOS package had never met the defect: it carries its
own copies.

`situer_tcl()` — in `emplacements.py`, with the other paths, because
`fenetre.py` imports Tk and no continuous integration runner starts it — sets
`TCL_LIBRARY` and `TK_LIBRARY` from `sys.base_prefix` when they are empty, and
touches nothing otherwise — a machine whose Tk comes from the system keeps its
own. The window now opens both ways, and `outils/preuve_fenetre.py` serves the
proof on both systems.

## Second pass over the interface, screenshots in hand (2026-09-03)

The first pass had removed the two defects reported (resizing,
scrollbars). This one starts from the screenshots of the five tabs, taken by
driving the real window, and keeps only what is verifiable — not matters
of taste.

| Defect | What it cost | State |
|---|---|---|
| The continuation lines in live restarted against the margin | A long line dropped back below the time and the name: the eye lost the text column, on the one tab you look at during a meeting | fixed — `lmargin2` at 90 px, the measured width of the time and the name |
| The voice naming field had **no** label | A grey rectangle next to a « Nommer » [name] button: nothing said that a first name goes in it, and not the voice number | fixed — « Prénom » [first name] label |
| The lists kept the "clam" border | A grey-green square-cornered edging against drawn buttons and drop-down lists: the "foreign part" already removed from the menus came back through the lists. `borderwidth=0` does nothing about it, the border comes from the three colours of the `Treeview.field` element | fixed — `bordercolor`, `lightcolor` and `darkcolor` set to the card background |
| Two wordings for the same microphone value | « automatique (le mieux entendu) » [automatic (the best heard)] at the top of the window, « Automatique — le mieux entendu au démarrage » [automatic — the best heard at start-up] in Réglages: the same choice looked like two different settings | fixed — a single wording |
| « Micro » as the row label under a « Micro » block | Repetition with no information, where the row should name what is being chosen | fixed — « Appareil » [device] |

What remains, and will not be pursued here: the empty state of the lists
(headers above nothing, without a word) and the general austerity, which comes
down to Tkinter's ceiling.

## The macOS bundle is self-contained and signed with a stable identity (2026-09-02)

Observation from use: « ça n'arrête pas de demander des droits » [it keeps
asking for permissions]. Three causes, each verified on the installed
application, not assumed.

| Cause | What it cost | State |
|---|---|---|
| **Ad hoc** signature (`codesign --sign -`): the application's identity is the hash of its binary | Every rebuild made it an unknown application — microphone and Outlook asked again, the machine's guard too | fixed — signed with a stable identity (`macos/identite-de-signature.sh`): an Apple certificate from the keychain, otherwise a local certificate created once |
| **Non self-contained** package: `Contents/lib` linked to `~/.local/share/uv/…`, `PYTHONPATH` pointed at the repository's `.venv` | Every launch and every auxiliary process (watch, live) read hidden folders that the machine's guard challenges; on 1 September a refused write (`Operation not permitted`) stopped live in the middle of a meeting | fixed — interpreter, standard library, dependencies and code copied into the package (measured: 56 MB + 181 MB), nothing points outside `/Applications` any more |
| The installer kept **its own XDG paths** (`~/.local/share/greffier`, `~/.config/greffier`) while the application had moved to Application Support | Re-run, it would have looked for the models in the wrong place and downloaded 1.6 GB again into a hidden folder; the configuration stayed in `~/.config` | fixed — a single definition, `greffier/emplacements.py`, with no dependency, read by the installer as by the application; the installer moves whatever is left behind |

Measured along the way: the ad hoc signature does not cover the native
libraries either, and a self-signed certificate imported without explicit trust
is not seen by `codesign` (« 0 valid identities ») — hence going through
`security add-trusted-cert`, which asks for the login password once.

What it costs: a code change only shows up in the application after a rebuild.
That is the behaviour of installed software; `.venv/bin/greffier` follows the
code for development.

The permissions macOS asks for **once** on first use (microphone, Outlook
automation) remain: no application escapes them. What disappears is their
return at every rebuild.

### Measured in the guard's rules file, not inferred

The guard's rules file keeps one line per granted
permission: protected path, program, program identity,
timestamp. So it carries the exact history of the dialogs endured.

| | Before | After |
|---|---|---|
| Rules written for Greffier during a single meeting (2026-09-01) | **174** | — |
| Different identities of the same binary that day | **10** | — |
| Rules written after a rebuild and a relaunch | — | **0** |
| Rules written by a complete chain, a meeting processed end to end | — | **2** |

Ten identities for a single program in one day: that is the ad hoc signature,
redone at every rebuild. The guard saw ten unknown programs and asked again for
each. The 171 rules bearing on `~/.local/` tell the other half of the problem.

After the fix, the binary is identified by the **certificate team**
(`QULSPZ72V4`), no longer by a digest: a single rule, on `~/Library/`. The two
remaining rules do not concern Greffier's data but Claude Code's configuration
file (`~/.claude.json`), accessed by the writer.

### What has been proven, and asks for nothing any more

A 45 s synthesised meeting, two voices, run **through the package's
executable** — therefore with the same process lineage as a double-click, which
the guard takes into account. Segmentation, transcription, voice
identification, writing, sending: completed. Then, separately, the two
auxiliaries that run in a loop during a meeting: the package's device lister,
three `ffmpeg` slices and one `whisper-cli` transcription, all reading and
writing in Application Support. **No new rule, therefore no dialog.**

### The writer's path must be stable, not merely present

The guard records the program's path as it sees it, without resolving symbolic
links. A tool installed by Homebrew lives under
`/opt/homebrew/Caskroom/<outil>/<version>/`: the path changes at every update,
the granted rule dies with the old version, and the dialog comes back — in the
middle of a meeting for `claude`, which writes the minutes. The same tool under
`~/.local/bin` is a link with a fixed name, which updates do not move.

`macos/construire.sh` therefore puts `~/.local/bin` **first** in the PATH baked
into the package. Measured: the package was writing with the Caskroom's Claude
Code 2.1.195 while 2.1.258 was installed under `~/.local/bin`; after the fix it
takes the second, and regenerating minutes writes no rule.

## Settings are made from the window, and the writer's model is a choice (2026-09-02)

The configuration was **read** from three sources and could be changed only by
hand or by the assistant, which wrote a `.env`. Setting your microphone meant
opening a file — for a tool whose promise is "install it and it works", that
was the last snag.

`greffier/reglages.py` can now **write** `config.toml`, in the same place the
rest of the chain reads from: two files that contradict each other are worth
less than no file at all. The file is regenerated, comments included, so those
never lie about the setting next to them; the previous version is kept as
`config.toml.precedent`. The write is atomic, because saving happens while a
meeting may be running, and a helper process reading a half-written file would
stop on a syntax error.

The **Réglages** tab offers microphone, transcription model and language,
writer and its model, recipient, live, appearance. What is a list —
vocabulary, words that are never first names — stays in the file: a form would
truncate them. `chemins` is deliberately never written: freezing those paths is
exactly what made a machine that had moved read the old folder.

| Defect | What it cost | State |
|---|---|---|
| The form ran past the window, with no scrollbar | Writing and appearance **out of reach**, with nothing to say so — seen on a screenshot | fixed — scrolling `Canvas`, the wheel bound to every child except the drop-down lists, which keep it for changing value |
| The theme was not a setting | The window followed the system, with no recourse | fixed — `apparence.theme`: `systeme`, `clair` or `sombre` |
| The writer's model was never asked for | Claude Code followed the personal setting of whoever installed it: the minutes changed writer with nobody deciding, and could draw on the top of the range | fixed — explicit `--model`, **`opus` by default** |

**Why the second of the range.** Writing from a transcription already cut up
and attributed is synthesis, not long reasoning. The first one produces the
same document while eating into a quota much faster: one meeting a day is
enough to feel it. The setting stays open both ways, and the installation
assistant asks the question, Claude subscription checked first.

Measured: a 676 px form in a 170 px area at the minimum window size, fully
reachable by scrolling; a faithful write-and-read-back round trip over the
seven sections, accents and quotation marks included; a write that fails leaves
the file in place intact.

## A skill for repairs, since the writer is Claude Code (2026-09-02)

Greffier depends on an authenticated Claude Code instance. So that is what one
turns to when a link gives way — and with nothing to read, it gropes about: it
cannot guess that the data lives in Application Support and not in a hidden
folder, that the bundle signature must stay stable, or that the default model
is the second of the range by design.

`skills/greffier/SKILL.md` carries that knowledge: start with `greffier
diagnostic`, where the logs and the state are, symptom by symptom what each
means, the two traps of the machine's guard with the command that measures
them, and the three checks to run before proposing a fix. The installer copies
it into `~/.claude/skills/greffier/` — a copy and not a link, since the
repository can be moved — and does not put it there if Claude Code is absent.

## Settings apply on their own, and the Claude account is visible (2026-09-02)

Three defects reported in use within the hour that followed the delivery of the
tab, all three real.

| Defect | What it cost | State |
|---|---|---|
| The « Enregistrer » button lived **inside** the scrolling area | It went below the window edge: you changed the theme, no button was visible, **nothing was written** — checked, `config.toml` had not moved since the day before | fixed — no button at all any more |
| A save button at the foot of the form | Wrong pattern: a settings panel applies live, like the system one | fixed — every list, checkbox and field saves on its own; the two text fields when leaving them or on validation, never on keystroke, otherwise an email address would produce twenty files and as many backups |
| The theme was only applied "at the next launch" | The setting appeared to do nothing | fixed — the window is repainted on the spot |
| Nothing showed or managed the Claude account | It is the one that writes: without a session, everything works except the minutes, and the failure only comes after the transcription | fixed — **Compte Claude** block: version, address, organisation, plan, and three actions |

**Repainting without relaunching.** Colours are read when each component is
built, several of them drawing themselves on a canvas: changing theme therefore
requires rebuilding the inside of the window. What carries the state does not
move — capture lives in a separate process, so do the live watch and the live
view, the displayed thread is re-read from the log. Two traps measured along the
way: the repaint is deferred until after the event returns, without which the
drop-down list just chosen would be destroyed in the middle of handling its own
event; and `Vumetre._pas`, re-armed every 30 ms, now checks that its canvas
still exists, otherwise each remaining step would raise a `TclError` in Tk's
loop. Proven on the real window, both ways: `#f5f5f7` → `#1a1a1d` → `#f5f5f7`,
tab kept, save confirmation moved to the new status line.

**Signing in opens a terminal.** Sign-in is interactive: browser, then a code to
paste. None of that is driven from a Tk window, and it should not be attempted.
A `.command` file opened by `open`, rather than an `osascript` driving Terminal:
the latter would require the « Automatisation » [Automation] permission, one
more system dialog for the same result.

`diagnostic.compte_claude()` reads the session file, never the network: the tab
displays it every time it opens, and a remote call would make it wait for
nothing. No token is read, only enough to recognise the account —
a test checks it.

## The interface goes through a review, and the language is no longer a free-text field (2026-09-02)

Four observations from use, three of which are measured rather than judged.

| Defect | What it cost | State |
|---|---|---|
| The palette had **no accent**: `accent` was the ink black | The window was uniformly grey and nothing guided the eye | fixed — an indigo, 6.83:1 on the card in light, 5.67:1 in dark, chosen far from the recording red and the level meters |
| The card's hairlines at **1.28:1** | Borders and separators invisible: the interface looked flat whatever you did | fixed — 1.50 and 1.44, with a test that keeps them perceptible |
| `ttk.Combobox`, with the grey square arrow of the "clam" theme | Next to the drawn buttons and scrollbars, it read as a part from somewhere else | fixed — `Liste`, drawn: same rounding, same edging, same hover, chevron in two segments, menu that extends the field |
| « Se connecter » [sign in] offered to someone already signed in | Suggests the session is not seen | fixed — a single action whose label follows the state; no more « Actualiser » [refresh] button, the state is read again when the tab is shown |
| The **language** was a free-text input field | « fr » cannot be guessed, and a mistyped code transcribed in the wrong language, silently, for an hour | fixed — a list of sixteen languages, automatic detection included |
| The bottom line kept « … en cours… » [in progress] | After a Claude Code update, it suggested the task was still running | fixed — the last task to finish clears it |

**An empty language means "recognise it yourself"**, the way an empty microphone
lets the listening decide. The two engines do not express it the same way, and
getting it wrong is silent: `whisper-cli` receives `-l auto`, faster-whisper
receives `language=None` — the string "auto" would be rejected there. Two tests
hold this correspondence.

`Liste` carries its own (key, label) pairs: the caller sets and reads **keys**,
never the displayed text. The previous version had to recover the key by
comparing labels, which broke at the first rename.

The README finally carries two **animated SVG** diagrams — the chain step by
step, and the five window views cycling past. They follow the reader's light or
dark theme through `prefers-color-scheme`, and stand still for anyone who asked
for less animation (`prefers-reduced-motion`). Nothing rasterised: the text
stays selectable and the file weighs a few kilobytes.

## A voice bank that contradicts itself must stop asserting (2026-09-02)

Observation in a real meeting: four voices for two people, and a first name
attributed to someone although nobody had spoken it. Measured on the recording,
not inferred from the symptom.

Voice prints identify people: this document designates them by **« A »** and
**« B »**, and names neither. The numbers are enough for the reasoning, and a
repository has no business carrying anyone's voice signature under their own
name.

### The first name came from the bank, not from the speech

| Live voice | Speaking time | against « A » | against « B » | Bank's verdict |
|---|---|---|---|---|
| v4 | 57.0 s | **0.78** | 0.94 | « A », margin 0.24 — asserted |
| v3 | 56.9 s | 0.46 | 0.55 | a third entry, margin 0.44 |

Both checks were satisfied, threshold and margin: the tool was not wrong to
assert, it was wrong to trust its bank. Because inside that bank:

| Bank pair | Similarity |
|---|---|
| « A » and « B » | **0.77** |
| the eight other pairs | 0.22 to 0.53 |

Two different people measure at 0.41 according to `docs/calibrage.md`. A pair at
0.77 says that one of the two names carries the other's voice. The « A » voice
print had been paid in eight days earlier from an 85 s cluster, in a meeting of
992 speaking turns where no channel had identified the local speaker — the
ground for a mix-up.

### What was fixed, and what was ruled out

**Ruled out: raising the threshold.** It would take knowing the similarity of
one person between two sessions, and the only high pair in the bank is precisely
the one under doubt. Choosing a number here would be guessing it, which this
project refuses to do elsewhere.

**Adopted: refuse to assert when the bank contradicts itself.**
`noms_en_conflit()` compares known people pairwise; any pair at the recognition
threshold means one name is wrong without saying which, and `reconnaitre()` then
no longer returns that name. The voice shows as a voice to name, which calls for
the human correction — the one source nothing argues with. Names outside a
conflict go on being recognised: one doubtful entry does not silence the whole
bank. The defect becomes visible instead of confirming itself on its own.

### Merging voices already existed, but nothing said so

Naming a voice with another one's name **merges** them: the speaking turns move
to the surviving voice, the voice prints add up — which enriches the entry paid
into the bank — and this holds for as many voices as segmentation created. The
correction menu did no more than display the name. It now announces
« ⟵ réunir les deux voix » [merge the two voices] on names already carried
elsewhere in the meeting.

### Live finally gets the second chance of re-stitching

Reported symptom: « il me détecte à chaque fois une voix différente » [it
detects a different voice for me every time]. Measured on the same meeting,
27 sentences, voice prints taken sentence by sentence.

| | Same person | Different people |
|---|---|---|
| Median | **0.69** | 0.35 |
| 1st quartile | 0.57 | 0.26 |
| Above the 0.75 threshold | **28 %** | 2 % |

The threshold was therefore **above the median for one and the same person**:
three times out of four, taking the floor again created a voice. Duration
explains all of it — the sentences in this meeting last 2 to 4 s at the median:

| Sentence duration | Median « same person » | Above the threshold |
|---|---|---|
| ≥ 1 s | 0.69 | 28 % |
| ≥ 3 s | 0.77 | 64 % |
| ≥ 5 s | 0.79 | 89 % |

**The threshold was not at fault, though, and nothing was recalibrated.** On the
accumulated aggregates, the two voices of the same person rise to **0.79** and
the two different people stay at **0.63**: at 0.75 the separation is clear.
Attaching a block compares one short voice print to a voice's aggregate, once,
and never redoes the comparison as the material accumulates.

`Fil.recoller()` redoes it, on every slice, by calling `fusionner_voix` — the one
from the final processing, same threshold, same minimum-material guard. Two
voices named by a human under different names are never merged: a human
correction is not undone on a measurement. The merge travels through the log
(`genre: "reunion"`), the window rebuilding the thread without ever computing a
voice print.

Checked by replaying the meeting's real thread: the four voices become three,
the 8 s voice joins the 56 s one of the same person — 13 speaking turns instead
of 10 — and the other person stays separate. The remaining voice, a single
5.3 s sentence at 0.60 and 0.52 from the other two, is genuinely ambiguous: one
click merges it, and the menu now says so.

## A meeting ended from the window left nothing behind (2026-09-02)

The most serious one of the day, and it explained several symptoms at once:
« ces réunions ne s'affichent pas dans la liste » [these meetings do not show
in the list], « le compte rendu ne dit pas qui était présent » [the minutes do
not say who was there].

**Saving to disk existed only in the command line.** `greffier traiter` deposited the
master file, the transcription and the minutes; the window called the same
chain and then wrote nothing. A meeting ended with the button was therefore
transcribed, written up, sent by mail — and lost: absent from the meeting list,
impossible to re-read, impossible to rename a voice afterwards, so nothing
entered the bank.

`Traitement` now keeps the meeting itself, behind a `DepotReunions` port and
two optional output folders. All its callers benefit from it, and the command
line does no more than say where. **Kept before the sending**: an unreachable
mail server must not lose an hour of transcription and its writing — a test
checks it.

### The context line is composed, no longer written

Two sets of minutes from the same day, both correct by the instructions:
« 2 septembre 2026, 15 h 50, durée 2 minutes. Participants : Tanguy, Paul. »
and « 2 septembre 2026, 3 min. » — no time, no participants. A date and a time
are not matter for style.

`entete_contexte` now composes the line and asks for it to be reproduced word
for word: date, **start and end times** (the end is deduced from the duration),
duration, participants. And when no voice has been named, it says **how many**
people spoke — « 3 personnes ont parlé, aucune nommée » [3 people spoke, none
named] — instead of leaving the question unsaid. Minutes that do not say who
was there leave their reader without an answer, and a missing name is corrected
with one click.

### A processing run no longer starts during a meeting

The state file is unique: it is through it that the window follows the meeting
in progress. A processing run started alongside publishes its own phases there,
up to « terminé » [finished], and the window concludes that the meeting is over
— the live thread stops and the listening processes withdraw, while the capture
goes on. Actually triggered that day, in a real meeting, by a processing run
started on the side. `greffier traiter` now refuses as long as a meeting is
recording, and `--quand-meme` remains for whoever knows what they are doing.

### Distorted words: what the writer is to do with them

The transcription sometimes renders one word as another that sounds the same
without existing (« diemandie » for « demander » [to ask]). Three rules, in
this order: restore the word when the sentence leaves no doubt, and without
flagging the correction; never quote a guessed form between quotation marks;
never guess what carries the information — a name, a figure, a deadline — but
flag it in an appendix rather than writing down an invented value.

### Still open

- **No way to delete a meeting** from the Réunions tab.
- **In person, the channel designates nobody**: measured on a real meeting, two
  of the three recorded channels are digital silence, the system loopback
  having nothing to pick up. Everything then rests on the voice prints, and
  nothing warns the user that this is the case.
- **The number of participants** is adjustable (it forces that many groups in
  the final processing run) but nothing suggests it when the detected count
  looks too high.

## First run on a real Linux machine (2026-09-08)

Ubuntu, PipeWire, GeForce GTX 1660 Ti, no CUDA library installed.
`python3 outils/installer.py --oui` runs to the end: `uv` installs CPython
3.13.13, the segmentation and voice print models download, `large-v3` is ready,
the configuration is written. What the container proof did not show, a desktop
machine showed straight away.

| Defect | What it cost | State |
|---|---|---|
| `device="auto"` picks the graphics card without checking cuBLAS | The chain **crashed** after eight minutes, `Library libcublas.so.12 is not found`, the meeting lost at the moment of being transcribed | fixed — fall back to the processor, a processor failure itself staying visible |
| The interface asked for "DejaVu Sans" and "DejaVu Serif" | The Tk that `uv` ships is built **without fontconfig**: it only exposes the historical X11 families, any other name falls back to `fixed`, a bitmap that does not scale | fixed — "Helvetica" and "Times", which Tk guarantees on all three systems |
| Font sizes were given in points | X11 reports close to a hundred dots per inch where macOS reports seventy-two: the same interface grew by a third, « Démarrer la réunion » overflowed its button, three labels ran past their frame, one of them 1341 px inside 787 px | fixed — negative sizes, hence in pixels, identical everywhere |
| Sound capture was judged on the presence of `pactl` | A machine with PipeWire running but without `pulseaudio-utils` was told that everyone else's sound could not be captured, when `ffmpeg -f pulse` records there perfectly well — checked both ways, microphone and monitor | fixed — the judgement is made on the server socket, or on `PULSE_SERVER` |

### Why the container proof had not found them

`preuve-fenetre-linux.Dockerfile` installs Debian's `python3-tk`: a Tk 8.6
built **with** fontconfig, which sees the seven DejaVu families and renders
them correctly. The installer installs `uv`'s interpreter and its Tk 9.0, which
sees none of them. Both paths are legitimate; only the second is the one
somebody installing Greffier follows. The container proof stays useful — it did
show that the window opens — but it says nothing about the rendering.

### The chain, measured

For want of `say`, the test dialogue was resynthesised with two Piper voices
then put through the real chain: **115 words, two voices, "Jacques" and "Sandy"
found**, which macOS already achieves.

### Then on real voices, not on synthesis

Two real interviews in French, taken from Wikimedia Commons, and a real work
meeting with four people. Synthetic voices are an easy test: they do not talk
over each other, do not move away from the microphone and have no background
noise.

| Recording | Length | Expected | Found |
|---|---|---|---|
| [Jean-Pierre Jaussaud interview](https://commons.wikimedia.org/wiki/File:Interview_Jean-Pierre_Jaussaud.ogg) (CC BY-SA 4.0) | 1 min 45 | 2 voices | **2 voices**, 323 words, 95 % coverage |
| [Alexandre Hocquet interview](https://commons.wikimedia.org/wiki/File:Interview_Alexandre_Hocquet_The_Conversation.ogg) (CC BY-SA 4.0) | 5 min 16 | 2 voices | **2 voices**, 802 words |

No name is invented: since nobody introduces themselves in these interviews, no
voice is named, and that is the intended behaviour.

Then a real work meeting, the hardest of the three: **ES2002a from the AMI
corpus** (CC BY 4.0), twenty-one minutes, four people around a table, and a
single channel where everything is mixed — exactly the configuration this
document flags further down as the one where the channel designates nobody. The
reference is not open to argument: the corpus ships four headset tracks, not
one more.

| | Expected | Found |
|---|---|---|
| Voices | 4 | **6** |
| Words | — | 2,499 |
| "Indéterminé" blocks | — | **42**, more than any single person |
| Speaking time | — | two voices carry 92 % of it |

The transcription itself holds: "I'm Laura and I'm the project manager", "Hi,
I'm David and I'm supposed to be an industrial designer". These are precisely
the sentences that name attribution looks for — but the patterns are French
(`je m'appelle`, `moi c'est`, `je suis`), and nothing recognises them in
English. This is not a defect: the tool is written for meetings in French. It
is worth saying, the transcription language being a setting.

What this measurement brings: the open point about the number of participants
is no longer an impression. On a single channel, with no announced count, four
people become six, and two passages in five are attributed to nobody.

What synthesis did not show: with no announced participant count, the grouping
over-splits a real conversation. The displayed count stays correct, but the
body of the transcription carries the raw labels.

```
sans « personnes »   [Personne 0] [Personne 1] [Personne 10] [Personne 13] [Indéterminé]
avec personnes = 2   [Personne 0] [Personne 1]
```

This is the point already open further down about the number of participants;
it now has figures, and on real speech.

### What the computation cost, and what it costs

Falling back to the processor keeps the chain alive, not usable: `large-v3` in
`int8` needed **eight minutes for thirty-eight seconds** of audio, thirteen
times real time — thirteen hours for a one-hour meeting. Two things explained
it, and neither was visible.

The card was there and unusable. No distribution ships cuBLAS and cuDNN with
the driver, and the `nvidia-*` wheels place their libraries outside the
loader's path: CTranslate2 did not find them. Settled by loading them by hand
when the model is mounted, `LD_LIBRARY_PATH` being no answer for a desktop
shortcut. The same file goes through in twelve seconds.

The bottleneck then became segmentation and the voice prints, which sherpa-onnx
ran on **a single thread**. Measured on the hundred-and-five-second interview:

| Threads | Time | Output |
|---|---|---|
| 1 | 287 s | 14 segments, 8 groups |
| 2 | 206 s | identical |
| 4 | **167 s** | identical |
| 8 | 193 s | identical |

Taking everything is worse than taking half, hence the rule kept. The result
does not change: only the time moves.

### Still open, on the Linux side

- **`skills/greffier/SKILL.md` is not in the repository.** Three
  `test_installeur.py` tests fail on a fresh clone, whatever the system: the
  file exists on the original machine without ever having been tracked.
- **`outils/fabriquer_reunion.py` depends on `say`**, hence on macOS: eighteen
  integration tests are skipped elsewhere. They are skipped twice over, since
  they also require `ggml-large-v3-turbo.bin` and `whisper-cli`, two
  whisper.cpp artefacts — so the Linux chain is never proven by them, full
  installation or not.
- **The theme follows macOS only**: `systeme_en_sombre()` returns `False`
  outside Darwin, so a desktop in a dark theme still gets the light interface.
- **The window has no font antialiasing**, and nothing in the code can give it
  any: the Tk of the interpreter installed by `uv` is built without Xft —
  `tk::pkgconfig get fontsystem` returns `x11`, and `tkfont.families()` counts
  only 48 families, no DejaVu. Apt's Tk returns `xft`, sees seven DejaVu
  families and antialiases. The text is therefore legible and in its place, but
  not crisp.

  One lead, which is a decision and not a fix: the whole source compiles under
  Python 3.12 (`python3 -m compileall src outils tests` passes, and nothing
  uses an API specific to 3.13), while Ubuntu 24.04 — the most widespread LTS —
  ships only 3.12. Lowering `requires-python` to `>=3.12` would allow using the
  system Python there, with its antialiased Tk. To be weighed against the macOS
  package, which rests on `uv`'s relocatable interpreter.

## The night before the national demonstration (2026-09-10)

A real meeting the previous evening — ninety-two minutes, three people around a
table — went wrong on every axis at once, and the report of it is what this
section answers. Every figure below was measured on that recording, not
supposed.

| Defect | What it cost | State |
|---|---|---|
| The segmentation produced **298 voices for three people** | thirty-six voices named by hand, and minutes announcing a crowd | fixed — three stitching passes, 298 become 21, of which 3 carry over ten seconds |
| Naming two voices the same name did not join them | each kept its identifier; the minutes announced two people of the same name | fixed — naming joins, the fuller voice keeping its identifier |
| A wrong name could not be taken back | overwriting adds a false print to the bank instead of removing one | fixed — a name can be removed |
| The bank held a person called **"A nommer"** | at 0.997 to Paul: the interface label had become a first name. Three pairs in conflict, and a conflict silences a name — Paul and Kevin were no longer recognised at all | fixed — first names are checked, and a print that resembles somebody else is flagged before it enters |
| Nothing said **which print** to remove | erasing a person over one bad print loses every good one | fixed — `empreintes_intruses`, and prints now carry the meeting they came from |
| No documents could be given mid-meeting | the assistant answered on the transcription alone | the button existed since 16:42; the installed package dated from 16:16. Rebuilt |
| The minutes never arrived | they had never been written: the writing was interrupted and nothing ever noticed | fixed — the window says which meetings are transcribed without minutes |
| The context line counted every fragment | "Participants: Fantin, Tanguy, Michel, and 295 unnamed voices" | fixed — only the voices that carried the meeting |
| The update button could not work | `construire.sh` never wrote `GREFFIER_DEPOT_SOURCE` into the bundle | fixed |
| **Linux: nothing worked** | without `uv`, the installer announced its fallback, skipped creating the environment, and called an interpreter that did not exist | fixed — the check is on the interpreter, not the directory. Proof rebuilt: 1351 tests pass in a bare container |

### What the tool gained

**It takes part.** Called by its first name it answers aloud, in 3.9 seconds
measured end to end, on the meeting's own content. Left alone it asks for a
voice it cannot place, and names that voice when somebody answers — the answer
stops being small talk and becomes a name in the minutes.

The hard half is the silence. Measured against the real writer: an ordinary
exchange gets none, a decision with no owner gets "Qui prend en charge la
migration en Symfony 7 ?", a question left hanging gets asked again before the
room moves on. Four refusals hold it back — never cut in, rest between
spontaneous turns, never repeat a question, never serve a remark about a subject
the room has left — and being called by name escapes all four.

The voice is Kokoro through the sherpa-onnx already loaded for segmentation:
no new dependency, no network, 4.9x real time. The system voice remains as a
fallback and everyone can hear that it is one.

### Still open

- **Windows has not been run on a real machine.** The code paths are there and
  the tests cover the decisions, but nobody has double-clicked the thing.
- **The live stitching is not the final one.** `Fil.recoller` runs on partial
  material during the meeting; the three passes added here run afterwards. A
  meeting still shows more voices while it happens than in its minutes.
- **No way to delete a meeting** from the Réunions tab.
- **In person, the channel designates nobody**: two of the three recorded
  channels are digital silence, everything rests on the voice prints, and
  nothing warns that this is the case.
- **The assistant cannot yet read the connected sources** (GitLab, Jira, Trello)
  when it decides whether to speak. It has them for a written question, not for
  a spoken one.

## The morning after, in use (2026-09-10)

What the night's work looked like once somebody tried to use it, and what came
out of it. Every figure is measured on the same 92-minute recording.

| Defect | What it cost | State |
|---|---|---|
| The live thread founded **a voice per sentence** | 111 voices for three people, and the cost of each attachment growing with them | fixed — 12 voices, attributions 92.9% right, 4.3 ms per sentence |
| The vocabulary questions were absurd | « J'ai entendu "bailleurs". Fallait-il comprendre "bailleur" ? » — a plural, an accent. Three questions in four were of that kind, so nobody read the fourth | fixed — 8 questions become 3 on the same 3,765 replies |
| Two buttons, one saying « Lucie participe » | it suggested she could choose not to, and removing it removed the only way to switch her on — she answered nothing and nobody could tell why | fixed — one button, for the voice; `actif` true by default |
| Rebuilding did not replace the running application | two hours spent looking for three buttons that had been in the bundle since morning | fixed — `construire.sh` relaunches, never during a meeting |
| `pointinghand` is a macOS cursor | a Tcl exception on every hover under X11 | fixed |
| A document handed over mid-meeting | reached the assistant only once the minutes were written | fixed — re-read on every question |
| A sentence written to be said went through the model | the acknowledgement that names a voice came back as a vague courtesy, dropping the name | fixed |

**A step back worth recording.** The live stitching had been wired to the final
chain's three passes. Replayed, that makes attribution accuracy fall from 93% to
**79.6%** — the level you would get by giving everything to the loudest voice.
After the meeting, adoption compares aggregates of minutes; live, aggregates of
two sentences, where 0.45 of similarity means nothing. The live thread is back
to `fusionner_voix`, and what bounds the number of voices is the ceiling and the
measured threshold.

### Still open, and why

- **The publication workflow has never run.** It waits in
  `outils/publier.yml.a-mettre-en-place`: an OAuth token without the `workflow`
  scope can neither create nor update a file under `.github/workflows/`, and
  GitHub rejects the whole push when one appears. Two `git mv` from an account
  that has the right, and it runs. Until then the Windows and Linux artefacts
  cannot be proven — GitHub's runners are this project's only Windows bench.
- **Gatekeeper will refuse the macOS bundle** on any other machine. The bundle is
  signed with a development certificate, not notarised. Fixing it needs a
  Developer ID, so a paid account: a decision, not a task.
- **The history still carries colleagues' first names** in the commit messages of
  the 88 commits that predate 2026-09-10. The files are clean; the past is not.
  An anonymised history exists and has no common ancestor with `main` — GitHub
  refuses a pull request between disjoint histories, and a merge would erase
  nothing anyway. Publishing it requires a force-push on `main`, which is a
  decision. The rewritten history is kept in
  `~/Documents/greffier-avant-anonymisation-2026-09-10.bundle`.
- **Windows has still not been run on a real machine.** Sixteen tests cover the
  system-specific paths — cursor, PowerShell literal, executable path, voice
  player — and `outils/lanceur_windows.py` answers `--version`. Nobody has
  double-clicked it.
- **No AppImage for Linux**, only the source tree and its installer.
- **The assistant does not read the connected sources** (GitLab, Jira, Trello)
  when deciding whether to speak. It has them for a written question, not for a
  spoken one. Nothing is configured on this machine, so building it would prove
  nothing.
- **`initiative` is off by default**, which means the proactive half — a decision
  with no owner, a question left hanging — ships disabled. It is measured and
  tested; it has never been through a real meeting.
- **Two voices merged by hand cannot be separated again.** Naming joins, and a
  name can be removed, but the join itself has no undo. It has not cost anything
  since the stitching stopped over-splitting, which is why it waits.
