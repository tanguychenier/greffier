# The plan, as boxes to tick

What is left to do on Greffier after 0.3.23, in the order each phase unlocks
the next. A box is ticked in the PR that finishes the point, with its proof
next to it: a measured figure, an image looked at, a test that would fail if
the behaviour changed. The detail of each point is in `what-is-left.md` and
`scenarios.md`; here, only the state.

## Phase 1. A real corpus in French

The synthetic meeting gives 1.75 % of errors whatever the decoding
combination: it tells nothing apart. Every setting waits for this phase.

- [x] Check the candidate corpora against four criteria: French, several
      speakers in one room, a reference text with the turns, a licence that
      allows the use. Leads: SUMM-RE, ORFEO, CID, ESLO, committee hearings of
      the Assemblée nationale (public video and minutes naming every speaker,
      under the Licence Ouverte).
      *Proof: a table in `corpus.md`, one candidate kept or refused per line, with the reason.*
- [x] Keep two or three recordings of 20 to 40 minutes covering the three
      causes of the complaint: overlap, accent, distance to the microphone.
      *Proof: a download script in `tools/`, never any audio in the repository.*
- [x] Write `tools/measure_corpus.py`: word error rate, rare terms found,
      speaker attribution accuracy (the 91.6 % figure of the AMI, through
      the same machinery as `replay_stitching.py`).
      *Proof: the table of the three figures per recording in `corpus.md`.*
- [x] Replay the sixteen decoding combinations and the vocabulary prompt on
      the real recordings; keep only what moves a figure.
      *Proof: the before/after table, and the default settings justified by it.*
      Measured on 2026-09-15: the chain fuses four people into two voices on
      the meeting with a fifth of overlap (64.1 % right, 23.9 % wrong); that
      case comes before any decoding setting. The sixteen combinations go
      from 21.5 % to 409 % on real speech: the product's setting is the best
      or within 0.6 point of the best, and nothing changes; the danger zone
      (conditioning without the temperature ladder) is written in `corpus.md`.

## Phase 2. Windows, seen for real

Sixteen tests cover the paths specific to the system; nobody ever
double-clicked.

- [x] On the Windows runner, launch `Greffier.exe` with no argument, wait,
      photograph the screen and bring the images back as an artefact (run by
      hand, never by a tag).
      *Proof: the images looked at: fonts, first-launch boxes, data folder under `%LOCALAPPDATA%`.*
      Done on 15/09 (`windows-proof.yml`). Looked at: the first question
      opens, but shows its key `modeles.manquants` instead of the sentence,
      and `demarrage.log` carries `'Window' object has no attribute 'loop'`.
- [x] Fix what the images show.
      *Proof: the images after, and one test per defect found.*
      Four defects seen and fixed on 15/09: the launcher called a method that
      no longer existed, the executable carried neither sentences nor sounds,
      the models question came before the window, three labels stayed
      hard-coded in French inside an English interface.
- [ ] The real double click: a Windows 11 evaluation virtual machine driven
      over VNC, or his own Windows disk. His call.
      *Proof: a line "launched on Windows on …" in the README, with what was seen.*

## Phase 3. `initiative` on a real meeting

Shipped disabled; the proactive half of the assistant has never been
through a sitting.

- [ ] Fetch the meeting of 2026-09-10 (six people, 3 878 s) from the Mac:
      audio, json and jsonl. It is not on this PC.
- [ ] Extend `tools/replay_live.py` to feed `watch.py` with the thread of
      sentences, `initiative` on, and log every time she would have spoken
      and what she would have said.
      *Proof: the log of the interventions on the real meeting.*
- [ ] Judge each intervention: right moment, useful, intrusive. Decide the
      default value on those figures.
      *Proof: the table in `what-is-left.md`, and the default setting that follows from it.*

## Phase 4. Two short product tasks

- [x] In a room: when the sound comes from a single take, the window and
      the minutes say the attribution rests on the voices.
      *Proof: a test in `test_window`, and the line in real minutes.*
- [x] Attendee count: when the voices heard exceed the number declared, the
      window suggests it.
      *Proof: a test on the synthetic meetings, and the suggestion seen on screen.*

## Phase 5. The post-meeting chain at the live threshold

Live gathered Lise into one voice; the post-meeting chain split her into
nine.

- [x] Measure with `replay_stitching.py`, on the AMI and on the phase 1
      corpus, the adoption of the small aggregates at 0.50 instead of 0.75.
      *Proof: the right / wrong / no opinion table, as for the "attached scrap". Kept only if both sides improve.*
      Measured on 15/09 with `tools/measure_stitching.py` on the two SUMM-RE
      meetings (the AMI files are no longer on this disk): the live threshold
      is the wrong lead (pairs at 0.50 fuse the same people a step earlier);
      the pass that fused four people into two is the consolidation at 0.70,
      inside the different-people range on this corpus (max 0.730) while the
      same person never scores under 0.932. Consolidation raised to 0.80;
      036c goes from 2 to 4 voices, 032a unchanged.

## Phase 6. The rest, afterwards

- [ ] Say it doubts at the moment it doubts.
- [ ] A first launch that takes you by the hand when nothing is configured.
- [ ] Group the stray voices under "Les autres".
- [ ] The GitLab, Jira and Trello sources for a spoken question (waits for
      a real configuration).
- [ ] An AppImage for Linux.
- [ ] The 22 skips of the integration suite: the table meeting with three
      timbres, and "Lucie" heard as "UCI".
- [ ] An up-to-date survey of speaker separation; any candidate has to beat
      +0.099 of margin at 14.6 ms.
- [x] The older documents of `docs/` put into English, like the code, and
      renamed: `what-is-left`, `scenarios`, `calibration`,
      `speaker-separation`, `graphics-card`, `retrospective-2026-09-10`
      (done on 15/09).

## Decisions that are his, not tasks

- macOS notarisation: a paid Apple account, otherwise Gatekeeper refuses the
  bundle on another Mac.
- The sound take: two microphones apart against the octopus one. To be
  measured on a labelled meeting before buying anything.

## Rules for the whole run

One PR per point on the protected `main`; CI green under `LANG=C` and xvfb
before every push; changelog regenerated by `tools/changelog.py`; one release
per finished phase; every figure announced is measured and written in `docs/`.
