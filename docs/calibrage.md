# Calibrating the voice recognition thresholds

The thresholds in `domaine/empreintes.py` are not intuitions: they come from a
measurement. This document states which one, so that it can be redone when the
hardware, the acoustics or the model change.

## Method

```sh
.venv/bin/python outils/calibrer_seuils.py <enregistrement.wav>
.venv/bin/python outils/verifier_fusion.py <enregistrement.wav>
```

The first segments the recording, extracts one voice print per speaking turn of
at least 3 s, then compares:

- **intra** — two samples of the same voice: must be high;
- **inter** — two different voices, aggregated voice prints: must be clearly
  lower.

The gap between the two distributions dictates the threshold. A first attempt
rebuilt the speaking turns from the speaker text file: the samples then
contained silences, the voice prints were noisy and the two distributions
overlapped almost entirely. **The exact segmentation boundaries must be the
starting point.**

## Measurement of 2026-08-24

Meeting of 2026-08-20, 11.8 min, about 6 participants, in a room, laptop
microphone, a single active channel (no system sound captured).

| | Median | Range |
|---|---|---|
| Two samples of the **same** voice | 0.74 | 0.62 – 0.79 on voices with ample material |
| Two **different** voices | 0.41 | up to 0.66 |

Hence `SEUIL_RECONNAISSANCE = 0.70`: above the worst case for distinct voices,
at the level of the common case for a single voice. The value of 0.55 chosen by
judgement before this measurement let confusions through.

## Measurement of 2026-09-09: the same person across two sittings

The measurement above compares two samples taken from **one** meeting. That is
the easier case, and it is not the one recognition depends on: what decides
whether a colleague is recognised at all is whether their voice print from last
week still matches this week's. That measurement was missing, and it is why
the threshold had never been questioned downwards.

The AMI Meeting Corpus supplies it. Its meetings come in series with the **same
participants**, each wearing their own headset microphone, so two "Headset-N"
files from two sittings of one series are the same person twice over, with no
annotation to interpret. `outils/calibrer_sur_corpus.py` runs it.

Series ES2002, sittings a and b, two participants, 240 s read from the middle
of each recording:

| | Range |
|---|---|
| Same person, **two sittings** | 0.444 – 0.730 |
| Different people | 0.072 – 0.184 |

On those six pairs the two clouds separated cleanly, which suggested any
threshold between 0.184 and 0.444 would do and that 0.70 was too high.

**Four series later, that conclusion does not hold.** ES2002, IS1000, TS3003
and ES2003 give 91 pairs instead of 6:

| | Range |
|---|---|
| Same person, two sittings (7 pairs) | 0.152 – 0.893 |
| Different people (84 pairs) | -0.035 – 0.652 |

The clouds now overlap, so **no threshold separates them**. What each one costs:

| Threshold | Not recognised | Confused |
|---|---|---|
| 0.70 (current) | 4 of 7 | **0 of 84** |
| 0.50 | 4 of 7 | 1 of 84 |
| 0.45 | 3 of 7 | 3 of 84 |
| 0.40 | 1 of 7 | 3 of 84 |

0.70 confuses nobody, but that table asks the wrong question -- and so did the
one before it. **Neither reproduces what the tool actually does.** Recognition
never compares two prints in isolation: it asks which of the known people a
voice resembles most, and whether it resembles them *distinctly* more than
anyone else. Threshold **and** margin, which `Correspondance.sure` has always
required and which had never been measured together.

Measured that way -- querying sitting b against a bank built from sitting a,
across all four series:

| Threshold | Recognised | Confused |
|---|---|---|
| 0.70 | 3 of 7 | 0 |
| **0.45** | **4 of 7** | **0** |
| 0.30 | 5 of 7 | 1 |

**The threshold moves to 0.45.** It recognises one more person and still
confuses nobody: of the two wrong matches in the corpus, one is rejected by the
threshold (0.338) and the other by the margin (0.041 of separation). The margin
is what makes a lower threshold safe, and it is why the pairwise tables above
looked worse than reality.

Declaring that a bank entry carries someone else's voice is a different
question and keeps the old value, as `SEUIL_CONFLIT = 0.70`. A conflict
silences a name, so declaring one lightly amounts to recognising nobody -- and
different people reach 0.652 in this corpus, which a 0.45 conflict threshold
would have treated as the same person.

One methodological caveat, and it matters: AMI does not guarantee that
participant N keeps the same headset from one sitting to the next. Some of the
"different people" pairs scoring 0.48 to 0.65 may well be the same person on a
different microphone number, which would mean the overlap is partly an artefact
of the labelling rather than of the voice prints. Confirming that needs the
corpus's own speaker annotations, which this tool does not read.

**Method matters more than the numbers here.** A first run took the extract as
it came and produced 0.149 for the same person against 0.280 for two different
ones -- overlapping clouds, which said the method was wrong, not the threshold.
An AMI headset also picks up the people across the table, and its wearer speaks
only a fraction of the time, so the extract mixed several voices with silence
and breathing. Keeping only the loudest quarter of one-second windows -- on
their own microphone the wearer is by far the closest -- separated the clouds.
Any voice-print measurement that skips this step measures nothing.

## Over-splitting and re-joining

Automatic segmentation produced **27 voices for 6 participants**. This is the
known defect of the approach: a person who shifts posture or moves away from the
microphone becomes a new group.

`fusionner_voix` re-joins the groups whose aggregated voice prints exceed
`SEUIL_FUSION = 0.75`, from the most obvious pair to the least obvious,
recomputing the aggregate after each merge. On the same recording:

```
AVANT : 27 voix distinctes sur 172 segments
APRÈS : 22 voix, dont 5 avec au moins 10 s de parole

  v0      6.1 min (54.7 %)  ← recolle v8, v14, v2, v26
  v4      2.6 min (23.3 %)
  v49     0.7 min ( 6.4 %)
  v32     0.6 min ( 5.8 %)  ← recolle v10
  v17     0.5 min ( 4.1 %)

plus fort rapprochement restant : 0.645 (v17 ↔ v4)
```

Five voices carrying the bulk, a credible split of speaking time, and the
strongest remaining match falls below the threshold: the re-joining stops at the
right place. This removes the need to state the number of participants by hand,
which until now was the setting the whole quality of in-person identification
depended on.

## Raw clustering threshold measured (2026-09-01)

The `threshold = 0.8` of `DiariseurSherpa` (passed to `FastClusteringConfig`)
had never been measured the way `SEUIL_RECONNAISSANCE`/`SEUIL_FUSION` above
are — it came from the sherpa-onnx examples. On a synthetic test set with three
speakers (`outils/fabriquer_cas_difficiles.py --cas trois-voix`, two close
timbres), it merged two distinct speakers into one at the raw clustering stage,
**before `fusionner_voix` even came into play**: segmentation returned only 2
voices for 3 people, and `fusionner_voix` cannot separate what has already been
fused upstream.

Direct measurement (`DiariseurSherpa.decouper` in isolation, outside the full
chain), on two fixtures — `deux-voix` (`outils/fabriquer_reunion.py`, existing
reference) and `trois-voix` — sweeping `threshold`:

| `threshold` | `deux-voix` | `trois-voix` |
|---|---|---|
| 0.30 | 3 voices (over-split) | 3 voices (correct) |
| 0.40 – 0.50 | **2 voices (correct)** | **3 voices (correct)** |
| 0.55 – 0.88 | 2 voices (correct) | 2 voices (wrongly merged) |
| ≥ 0.90 | 1 voice (wrongly merged) | 1 voice (wrongly merged) |

The meaning of the parameter is counter-intuitive: the **lower** it is, the more
sensitive the clustering and the more voices it tells apart, up to over-splitting
at 0.30. The range `[0.40 ; 0.50]` is correct on both fixtures.
`threshold = 0.45` chosen (middle of the range). To be revalidated on a real
recording via `outils/calibrer_seuils.py`/`outils/verifier_fusion.py` — this
measurement covered only speech synthesis.

## Material guard before merging

A complement to the setting above, not its replacement: `fusionner_voix`
(`domaine/empreintes.py`) merges two groups as soon as their aggregated voice
prints exceed `SEUIL_FUSION`, without looking at how much material backs each
aggregate — an aggregate drawn from two or three seconds is noisy, and its
similarity with another small group is no longer a reliable signal. The function
now requires, on top of the score, that the **larger** of the two candidate
groups carry at least `MATIERE_MINIMALE_FUSION = 6.0` s (twice `DUREE_UTILE`)
before accepting the merge. The asymmetry is deliberate: a voice already
established (`v0`, 6.1 min in the measurement above) keeps absorbing thin
fragments with no new constraint; only two small groups still fragile can no
longer merge with each other on a statistical accident. Starting value, to be
revalidated by the same method as above.

## Known limits

- The voice print model is `nemo_en_titanet_large`, trained on English. It works
  on French voices — timbre depends little on the language — but a multilingual
  model would be preferable.
- A single meeting measured, in a room. The thresholds must be rechecked on
  video calls, where the signal is much cleaner and where the intra values
  should rise.
- Voices totalling less than 10 s of speech stay fragmented: too little material
  for a stable voice print. They must be presented as undetermined rather than
  as participants.
