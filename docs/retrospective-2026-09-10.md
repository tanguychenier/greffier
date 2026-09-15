# Retrospective of the meeting of 10 September 2026

A prioritisation workshop, 1 h 42, eight people around the table, an octopus
microphone. The meeting was recorded, transcribed, attributed and written up
from start to finish. This document does not tell the sitting: it gathers
what the data of this meeting **measured**, including the two times the
measurement contradicted what I thought.

Everything below can be replayed: `tools/replay_stitching.py`,
`tools/compare_extractors.py`, and the voiceprints cached in
`/tmp/greffier-empreintes/`.

## 1. What worked

| | Measure |
|---|---|
| Transcription | 16,547 words, 1,674 utterances, 1 silent passage in 91 min |
| People found | **6 out of 6** carry the meeting, one voice each |
| Attribution accuracy, live replayed in time order | **97.0 %** (576/594) |
| Accuracy with mature aggregates | **99.3 %** (555/559), 4 confusions |
| Minutes | 22 KB, 20 decisions, 12 actions with an owner |

The minutes themselves are good: decisions, actions with an owner and a
date, open points, and the badly transcribed terms flagged in an appendix
rather than guessed.

## 2. The four defects found, and fixed the same day

### "Lise" on nine voices

The post-meeting chain concluded "Lise" on **nine distinct voices**, eight
of them of a single turn. The minutes therefore announced "and 9 unnamed
voices" and eight attendees too many.

The voiceprint stitching had done what it could: the two test voices are
**0.700** from each other, under the stitching threshold, and **0.92** from
the person in the bank, hence both recognised. What the voiceprint cannot
say, the name says. The rule existed for live, it was missing from the
post-meeting chain.

| | before | after |
|---|---|---|
| named voices | 16 | **8** |
| voices announced | 17 | **9** |
| "unnamed voices" | 9 | **1** |

The unnamed voice left carries 112 s of speech: it really is somebody who
spoke for two minutes without being named.

### The state stuck on "sending" for two hours

Sending failed at 12:17. Seen live: the process at 0 % CPU, no thread at
work, no network connection open, and `etat.json` still saying "Envoi du
compte rendu…". Nothing was lost, everything is written before sending, on
purpose, but:

- the failure was only reported by a **modal window**, and the note was
  only written **after** the click; screen locked, nobody to click;
- **nobody published the next phase**.

Yet everything reading that state believed a meeting was still being
processed: the watch, the command line, and the rebuild of the application,
which precisely refuses to restart during a meeting. **That is one of the
reasons behind "updates do not work".**

### The rebuild left the machine without an application

Three defects stacked in `macos/construire.sh`, traced the same day:

1. The script asks the application to quit, then calls `pkill` to be safe.
   Under `set -euo pipefail`, a `pkill` that finds nothing returns 1, and
   finding nothing is **the normal case**. The script died just before the
   relaunch.
2. The check "was the application running?" was done **after** the build.
   Yet building kills it: macOS shoots down a process whose signed
   executable has just been replaced. The check therefore always saw "not
   running".
3. The relaunch was **announced, not checked**. `open` returns 0 without
   launching anything as long as macOS considers the application to be
   shutting down.

### Joining two voices was irreversible

Joining two voices took one click and nothing undid it: the absorbed voice
was deleted, the two sets of voiceprints poured into the same heap. Two
people joined by mistake stayed joined all the way into the minutes.

While wiring the way back, three defects appeared in the thread recovery,
the one that recovered 646 turns at the fiftieth minute. The worst: replaying
the log wrote "v1", "v2"… **without advancing the identifier counter**,
whose contract is never to reuse one. The next voice the thread founded was
therefore called "v1" again and **overwrote** the existing entry: the turns
of two people under one identifier, with nothing to flag it. Every thread
recovery was affected.

## 3. Two times the measurement contradicted me

This is the useful part of the retrospective, and it deserves to be written
as it happened.

### "Pascal carries 64.5 % of the speech, that must be several people"

58 minutes out of 91 for one person seemed a lot. I measured the **internal
coherence** of every large voice: how much each excerpt resembles the
aggregate of its own voice. A voice mixing two people would have a **lower**
coherence than the others, since its aggregate would fall between two
clouds.

| voice | internal median | 1st decile | foreign excerpts |
|---|---|---|---|
| **Pascal** | **0.835** | 0.665 | 12 / 424 |
| Serge | 0.815 | 0.613 | 1 / 40 |
| Arnaud | 0.802 | 0.500 | 3 / 24 |
| Bastien | 0.788 | 0.573 | 3 / 67 |
| Tanguy | 0.768 | 0.674 | 0 / 23 |
| **voice 162, unnamed** | **0.624** | 0.516 | 2 / 25 |

Two different people sit between 0.18 and 0.63. Pascal's voice is **the
most homogeneous of all**. He was running the workshop: he really did speak
for 58 minutes. The suspicion was false, and it had to be checked before
touching a threshold.

The measurement, on the other hand, pointed at **another culprit**: voice
162, the one left unnamed with 109 s of speech, falls to **0.624**, far
below all the others. That is the one mixing several people. The suspicion
was not baseless, it was aimed wrong, and that is exactly what this tool is
for: `tools/voice_coherence.py`.

### "The errors are at the start, when the aggregates are thin"

A reasonable hypothesis: live only knows the past, so it should be wrong
mostly at the beginning. Replayed in the true order of time:

| slice | minutes | accuracy |
|---|---|---|
| 1/6 | 0 → 12 | 97.0 % |
| 2/6 | 12 → 24 | 98.0 % |
| 3/6 | 24 → 36 | 97.0 % |
| 4/6 | 36 → 47 | 97.0 % |
| 5/6 | 47 → 61 | **93.9 %** |
| 6/6 | 61 → 88 | 99.0 % |

`tools/replay_live.py 2026-09-10_10h10_reunion`

No start-up gradient. The dip is **in the middle**, not at the start. So the
maturity of the aggregates is not the limit, and a retroactive
re-attribution of the first sentences would bring almost nothing. It was,
however, the first thing I was going to build.

## 4. The bench of extractors: the answer settles it

The choice of the voiceprint model decides everything downstream, and it
had been made once at the start of the project without ever being measured
again. Four candidates on the 931 turns of this meeting, 2.5 s windows.

What counts is not the accuracy on a speaker verification set, where all
these models are excellent. It is **the margin**: the room left between the
first decile of "same person" and the ninth decile of "different people".
Negative, no threshold separates them.

| model | same (median / 1st dec.) | other (median / 9th dec.) | margin | ms/excerpt |
|---|---|---|---|---|
| **titanet_large** (in place) | 0.675 / 0.450 | 0.228 / 0.351 | **+0.099** | **14.6** |
| campplus_LM | 0.950 / 0.730 | 0.941 / 0.968 | **−0.238** | 9.3 |
| resnet293_LM | 0.925 / 0.832 | 0.876 / 0.937 | **−0.105** | 70.5 |
| eres2netv2 | 0.762 / 0.613 | 0.398 / 0.503 | +0.109 | 28.7 |

**CAM++ and ResNet293, both at the top of the speaker verification
rankings, are unusable here.** Their similarities are crushed between 0.94
and 0.97: on short excerpts taken in a room, they find everybody alike. A
verification ranking says nothing about what is needed here.

ERes2NetV2 gains **0.010 of margin for twice the computing time**, and it
is a model trained on Chinese. **TitaNet stays**, and it is now measured
rather than assumed.

## 5. What is left, by order of value

### The takes, and that is the first point

The octopus microphone is the worst possible case: it hears everybody **at
the same level**, so it destroys the information that would separate the
voices. Two microphones apart would give a difference in time of arrival
between them, a **physical** measure, independent of timbre, where all the
rest of the chain is statistical. A person sitting on the left stays on the
left for the whole meeting.

To measure before buying anything: two USB microphones 1 m apart, a
labelled meeting, and the question "does the difference in time of arrival
separate better than the voiceprint?".

### The six scraps of live

Six people carry the meeting, one voice each. Six stray voices remain,
totalling **89 s out of 3,878, that is 2.3 % of the time**:

| voice | turns | seconds | content |
|---|---|---|---|
| v3 | 7 | 37 | mixed, 4 people |
| v11 | 2 | 25 | mixed |
| v5 | 1 | 16 | Serge |
| v12 | 2 | 9 | mixed |
| v8 | 1 | 5 | Arnaud |
| v10 | 1 | 4 | Jonas |

Two of them are under the 6 s of the recognition threshold, so they carry no
name, which is already the right behaviour. Grouping them under "Les
autres" rather than counting them as voices would be the next gain, and it
is small.

### Live did better than the post-meeting chain

The most instructive fact of the day, and it is counter-intuitive. On the
same meeting, **the live thread gathered Lise into a single voice**: v3,
eleven turns, all her fragments together, while the post-meeting chain split
her into **nine**.

The reason is in what is compared. Live compares a **sentence** to an
aggregate that grows, with a threshold at 0.50; after the meeting two
**aggregates** are compared, with a threshold at 0.75, and each of Lise's
fragments is its own tiny aggregate, which resembles nothing enough. The
high threshold protects the large voices and abandons the small ones.

Hence the namesake rule, which catches after the fact what live already
knew. But the underlying lead is there: the post-meeting chain would gain
from **adopting the small aggregates** at the live threshold rather than at
the stitching one. (Measured on 2026-09-15 on the SUMM-RE corpus,
`corpus.md`: the lead was wrong there, the pass that fused people was the
consolidation, not the pairs threshold.)

### What has never run for real

- **`initiative`**: shipped disabled. Lucie answered correctly twice when
  called; the proactive half has never served in a sitting.
- **The Windows and Linux executables**: the commit is ready on the branch
  `ci/publication-des-executables`, blocked by the token's `workflow`
  right. `gh auth refresh -h github.com -s workflow` unblocks it. (Published
  since: the release carries the three artefacts.)
- **macOS notarisation**: the bundle is developer-signed, not notarised.
  Takes a paid Apple account.
- **The assistant does not read the connected sources** (GitLab, Jira,
  Trello) when it decides to speak.

### The state of the art, to review together

What I know stops at May 2026. The bench above settles the question of the
voiceprint model; it says nothing about what could replace the pipeline
itself, the end-to-end approaches and those that keep "who has just spoken"
as a state. An up-to-date survey remains the first point of that
discussion, and the bench table is its starting point: any candidate now has
to beat **+0.099 of margin at 14.6 ms**.
