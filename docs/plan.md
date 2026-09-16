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

- [x] Say it doubts at the moment it doubts. Done on 16/09: the engine's
      figure travels with each live turn, log and replay included, and the
      window marks the doubtful sentence « (?) » as it appears, the way the
      transcript did the next day.
- [x] A first launch that takes you by the hand when nothing is configured.
      Done on 16/09: the Conversation tab lists the three things to do, in
      order, the models, the account, a microphone, ticks them as they get
      done, and says once that everything is in place. Five tests on the
      real window; `docs/scenarios.md` had it under « What the tool should have ».
- [x] Group the stray voices under "Les autres". Done on 16/09: an unnamed
      voice under a twentieth of the speaking time, once three voices carry
      the meeting, is « Les autres » in the transcript and not counted as
      an attendee; the warning that suggests giving the count says so.
- [x] The GitLab, Jira and Trello sources for a spoken question (waits for
      a real configuration). Done on 16/09 for GitLab and Jira, read for
      her the way the documents are, the token pasted in the window; Trello
      is not a registered kind.
- [x] An AppImage for Linux. Done on 16/09: `tools/build_appimage.py`
      (PyInstaller, the same command as the Windows executable, then
      appimagetool), a job in `release.yml` that runs it on `--version`;
      built here and opened on a virtual screen, 382 MB, the window with its
      French sentences on a fresh home.
- [ ] The 22 skips of the integration suite: the table meeting with three
      timbres, and "Lucie" heard as "UCI".
- [x] An up-to-date survey of speaker separation; any candidate has to beat
      +0.099 of margin at 14.6 ms. Done on 16/09, section 4 of
      `speaker-separation.md`: within the tool's constraints (ONNX, no
      PyTorch, a licence a company can ship) nothing has changed; the one
      candidate worth exporting and measuring is ReDimNet (MIT); pyannote
      community-1 would need PyTorch, DiariZen is non-commercial, Sortformer
      stops at four speakers.
- [x] The older documents of `docs/` put into English, like the code, and
      renamed: `what-is-left`, `scenarios`, `calibration`,
      `speaker-separation`, `graphics-card`, `retrospective-2026-09-10`
      (done on 15/09).

## Phase 7. A faithful replay, live words, Lucie's speed, the project manager's day

Asked on 2026-09-16, from use: the live words did not match what was said,
Lucie took one to four seconds to answer, the context did not seem to work,
and none of it can be reproduced without holding a meeting. Every box below
is played on a recording replayed as if it were being captured, so that a
meeting is never needed to see what a meeting does.

- [x] Identifiers in English in `src/`: the last French names
      (`AVERTISSEMENT_SANS_BOUCLE`, `SEUIL_MUET_DB`, `_preciser_les_canaux`
      and some sixty others), renamed with the tests as the net.
      *Proof: no French identifier left by the scan, suite green.*
- [x] A replay bench: a recording fed through the live chain as the
      microphone would feed it, in real time or faster, window and assistant
      included, so that what happens in a meeting happens on the bench.
      *Proof: `tools/replay_meeting.py` on the synthetic meeting and on the corpus, and an e2e test that replays one and gets minutes out.*
      Done on 16/09 as a product command rather than a tool: `greffier rejouer
      <recording>` hands the file to the encoder in place of the microphone
      (`ffmpeg -re`), so the chunks, the watch, the live thread, the assistant
      and the final processing are the product's own, untouched.
      `tests/integration/test_replay_e2e.py` replays the synthetic meeting and
      checks the recording's length, the live thread's words and the minutes.
- [ ] Live words measured: the live transcript against the reference, next
      to the post-meeting one, per slice length, cut on silence or on the
      clock, with and without the previous slice as context.
      *Proof: the table in `corpus.md`, and only what moves the figure kept.*
- [ ] The same person across two meetings: named on one SUMM-RE meeting,
      recognised on the next of the same series; and one person whose tone
      changes inside a meeting, held as one voice.
      *Proof: the recognition rate across 032a → 032b, the coherence figure per person.*
- [x] Lucie's speed, measured end to end on the bench with synthesised
      questions, then cut: the slice ends when the speaker stops rather than
      on the clock, the answer streams to the voice as it comes, a faster
      model for what is spoken, the process kept warm.
      *Proof: the time from the end of the question to the first spoken word, before and after, in `corpus.md`.*
      Done on 16/09: `tools/measure_assistant.py` times the three steps on a
      replayed meeting. One Claude process kept warm for the meeting with the
      guidance as its system prompt (the model's share from 3.6 to 7.7 s down
      to 1.4 to 2.4), the listening pass on its own thread and run the moment
      the room goes quiet, the turbo model for the live thread where the card
      takes the large one, the voice and the live model opened before the
      first word. From 9.5 s to 5.7 s on this card; the streamed answer was
      not needed to get there and stays on the list below.
- [x] Context, as scenarios on the bench: a document handed over is used in
      an answer; a web search is made and its source named; a company source
      (GitLab, Jira, Trello) is read when its token is there; when it is not,
      Lucie asks for the access, gets it from the window, and says what she
      did with it.
      *Proof: one e2e test per scenario.*
      Done on 16/09: the registered sources (GitLab, Jira) are read for her
      the way the documents are (`company_sources`), a source without a
      token is named to her as such and she asks for it, the token goes in
      Réglages ▸ Sources d'entreprise. Four scenarios played against the
      real model in `test_context_scenarios`; what she said is in
      `scenarios.md`. Trello is not a registered kind and stays open.
- [x] The project manager's day, listed and covered: before the meeting
      (documents, agenda, who will be there, what to look up), during
      (questions, decisions, actions, look-ups), after (minutes, tickets,
      follow-up), each scenario in `scenarios.md` with its state.
      *Proof: `scenarios.md` extended, every open line either covered or measured.*
      Done on 16/09: twenty-seven lines in three tables, before, during,
      after; what was missing on the way was built (`greffier tickets
      --creer` creates the offered tickets on a source registered in
      writing, one yes each: the adapters existed and nothing called them).
      Four lines stay open and say so: the calendar, a comment on a ticket,
      a meeting joined from its invitation, her initiative on a real meeting.
- [x] The badge on the Conversation tab counts what has not been seen, not
      everything Lucie ever said: read her message, switch tab, one more
      message arrives, the badge said three where one was new.
      *Proof: a test on the count after a tab is opened, and the badge looked at.*
      Done on 16/09: the window notes which questions were on screen while the
      tab was open, and the badge counts the others. Four tests on the real
      window; the one with « one more after a look » fails on the previous code.
- [x] Test coverage measured per layer and raised where it is thin; the e2e
      suite around the bench runs where the models are and skips cleanly
      where they are not.
      *Proof: the coverage figure before and after in `what-is-left.md`.*
      Done on 16/09: from 74.4 % to 79.3 % overall, the command line from
      30 % to 46 %, the window from 44 % to 55 %; the table per layer and
      what stays thin, and why, in `what-is-left.md`.

## Decisions that are his, not tasks

- macOS notarisation: a paid Apple account, otherwise Gatekeeper refuses the
  bundle on another Mac.
- The sound take: two microphones apart against the octopus one. To be
  measured on a labelled meeting before buying anything.

## Rules for the whole run

One PR per point on the protected `main`; CI green under `LANG=C` and xvfb
before every push; changelog regenerated by `tools/changelog.py`; one release
per finished phase; every figure announced is measured and written in `docs/`.
