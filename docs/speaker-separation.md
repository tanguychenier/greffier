# Telling voices apart: what we do, what exists, what has not been measured

A working document, to be discussed. It keeps apart three things the
conversation readily mixes: what the tool does today and at what price, what
the state of the art offers, and what would have to be measured before
changing anything.

**Warning about the second part.** What I knew of the state of the art
stopped at May 2026. Section 4, added on 2026-09-16, is the survey brought
up to date on the sources of the day; the second part is left as it was,
for what it says of the principles.

**Since then:** the bench of extractors was run on a real meeting of 1 h 42,
and it settles the question of the voiceprint model. CAM++ and ResNet293,
both at the top of the speaker verification rankings, have a **negative**
margin on 2.5 s excerpts, no threshold separates them. TitaNet stays. See
[the retrospective of 10 September](retrospective-2026-09-10.md), section 4: any
candidate now has to beat **+0.099 of margin at 14.6 ms per excerpt**.

## 1. What the tool does

Three stages, each measured on a real 92-minute meeting of three people
around a table.

| Stage | What decides | Measure |
|---|---|---|
| Segmentation | pyannote-segmentation-3.0, clustering threshold 0.45 | 298 groups returned |
| Voiceprints | NeMo TitaNet large, 192 dimensions | sentence / aggregate: 0.667 against 0.337 |
| Stitching | pairs (0.75), adoption (0.45), consolidation (0.80 since 15/09, see `corpus.md`) | 298 → 21, 3 of them real |
| Live | attachment (0.50), ceiling of 12 voices | 111 → 12, 92.9 % accuracy |

The principle holding everything: **over-segmenting then stitching back is
reversible; under-segmenting is not.** The fine segmentation is kept and
repaired afterwards.

### What this pipeline ignores

Two pieces of information, available and free, that no stage uses.

**Who has just spoken.** A turn rarely follows itself, and almost never
after a ten-second silence. Our attachment compares a voiceprint to
aggregates, and nothing else: two consecutive sentences are treated as if
order did not exist.

**Where the person sits.** Two channels would give a difference in time of
arrival, which is a physical measure and not a statistical resemblance. An
octopus microphone in the middle of a table destroys precisely that
information: it hears everybody at the same level, comfortable for
transcription and ruinous for separation.

## 2. What exists

### The voiceprints

The catalogue of the engine already installed (`sherpa-onnx`) carries
twenty-one voiceprint models, nine of them WeSpeaker and nine 3D-Speaker.
Our TitaNet is one of the oldest of the lot.

| Family | Notable models | Size |
|---|---|---|
| NeMo | titanet_large (in place), titanet_small, speakernet | 23 to 101 MB |
| WeSpeaker | CAM++_LM, resnet34_LM, resnet221_LM, resnet293_LM | 26 to 114 MB |
| 3D-Speaker | CAM++, ERes2Net, ERes2NetV2 | 26 to 220 MB |

These models are reputed better than TitaNet on speaker verification
benchmarks. **That is not our benchmark**: those bear on excerpts of several
seconds, spoken alone in front of a microphone. Ours is a two-second excerpt,
in a room, with noise and overlaps. Hence `tools/compare_extractors.py`,
which measures the only thing that matters to us: the gap between "same
person" and "different people" on short excerpts.

None of these models is trained on French. That matters less than it seems:
a voiceprint carries the timbre, not the language, but it deserves to be
checked rather than assumed.

### The clustering

- **Agglomerative clustering** on the embeddings, what sherpa does and what
  our stitching extends. Simple, with no memory of time.
- **VBx / VB-HMM** (BUT Speech): variational Bayesian clustering with a
  hidden Markov model over the sequence of speakers. That is exactly the
  information we ignore, temporal continuity, and it is the standard of the
  best systems of the DIHARD campaigns. **The most direct lead for our weak
  point.**
- **Multi-scale** (NeMo MSDD): comparing at several window lengths at once,
  from 0.5 to 3 seconds, and weighting. Answers precisely our problem, where
  a short window is noisy and a long one straddles two speakers.

### The end-to-end approaches

- **EEND** and its successors handle overlapping speech natively, which our
  chain does not do at all: a sentence straddling two people designates
  nobody with us.
- **Sortformer** (NVIDIA) and **FS-EEND** aim at live, with low latency and
  a number of speakers not known in advance.

These approaches would replace two of our three stages. They have to be
available in ONNX to fit the project's constraint: local, light, no new
dependency, which remains to be checked.

## 3. What should be measured, in this order

From the least to the most expensive, each measurable on the labelled corpus
we already have.

1. **Changing the voiceprint extractor.** One configuration line, one model
   to download, and `tools/compare_extractors.py` gives the answer. If the
   margin between the two distributions widens, every threshold benefits at
   once.
2. **Taking the previous speaker into account.** A penalty on speaker change
   is enough to get the idea, before considering a full VB-HMM.
3. **Extracting at several scales.** Two windows instead of one, averaged or
   weighted. The cost doubles; it is 4.3 ms per sentence today.
4. **Revising the attributions already shown.** The thread can be replayed
   (`rejouer()`), so it is feasible without touching the rest. Nobody has
   measured it.
5. **Two microphones instead of one.** To measure before buying: a trial
   recording at two capture points would say at once what the difference in
   time of arrival brings.

### How to judge

Three figures, and not one more, all available on the labelled meeting:

- **the margin** between the first decile of "same person" and the ninth of
  "different people". Negative, no threshold separates them;
- **the number of voices** returned, against the number of people present;
- **the attribution accuracy**, the share of sentences in a group that is
  mostly right.

And one rule: **no threshold change without the measurement that goes with
it.** Three of the four thresholds of this project were first set by guess,
and all three were wrong.

## 4. The survey, brought up to date on 2026-09-16

What the warning at the top asked for. Checked on the day, on the sources
named; the figures are the authors' own, on public benchmarks, and none of
them was run here.

### Whole pipelines

| Pipeline | What it is | DER, AMI-SDM, no collar | Licence of the weights | Runs on |
|---|---|---|---|---|
| pyannote 3.1 (ours, through sherpa-onnx) | segmentation 3.0 + embeddings + clustering | 22.4 to 22.7 % | MIT | ONNX, no PyTorch |
| pyannote **community-1** (pyannote.audio 4.0, 2026) | same shape, WeSpeaker embeddings, VBx clustering, "exclusive" output for transcription | **19.9 %** (17.0 % on AMI-IHM, 20.2 % DIHARD 3) | CC-BY-4.0 | PyTorch |
| pyannote **precision-2** | the commercial one | 15.6 % | paid API | their servers |
| **DiariZen** Large-s80-v2 (BUT, 2025-26) | pruned WavLM-Large + Conformer + VBx | **13.9 %** (14.5 % DIHARD 3) | **CC BY-NC 4.0**, non-commercial | PyTorch, CUDA |
| NVIDIA **Sortformer** | end-to-end, one Transformer | strong on the authors' figures, not on the public comparative benchmark | open | PyTorch; **four speakers at most** |
| Rev **reverb-diarization v2** (in sherpa-onnx since 12/2024) | pyannote 3 fine-tuned, WavLM features | "22 % less WDER than pyannote 3.0" on Rev's own suites | **non-production licence**, commercial licence on request | ONNX |

### Voiceprints

The sherpa-onnx catalogue of speaker models has not moved since October
2024: the same nine WeSpeaker, nine 3D-Speaker, three NeMo. The two at the
top of that list, CAM++ and ResNet293, were benched here on a real meeting
and lost to TitaNet on short excerpts (negative margin, see section 1).

One new architecture stands out since: **ReDimNet2** (IDRnD, March 2026,
Interspeech 2026), 0.29 % EER on VoxCeleb1-O with 12 M parameters, 0.57 %
with 3.6 M. The first ReDimNet's code and weights are MIT; ReDimNet2's
weights are announced as released, without a licence named in the paper,
and neither has an ONNX export.

### What follows from it

Within what the tool is built on, ONNX through sherpa-onnx, no PyTorch, a
licence that allows a company to ship it, **nothing has changed since the
retrospective of 10 September**: the segmentation stays pyannote 3.0, the
voiceprints TitaNet, and the bar for any candidate stays +0.099 of margin at
14.6 ms per excerpt, measured on the real meeting.

Two things would be worth a measurement, in this order:

1. **ReDimNet (b2 or b3, MIT) exported to ONNX**, run through
   `tools/compare_extractors.py` on the labelled meeting. The only new
   candidate that fits the constraints; its author's figures are on clean
   VoxCeleb, and the bench here is on 2.5-second excerpts round a table,
   which is where CAM++ and ResNet293 fell.
2. **pyannote community-1**, if the tool were to carry PyTorch: three DER
   points on AMI-SDM, and the "exclusive" output made for reconciling with
   a transcription. That is a decision about the size of what is shipped
   (PyTorch is two gigabytes and a graphics card story of its own), not
   about a model, and it is his.

DiariZen would be the biggest gain (eight DER points on AMI-SDM) and is out
of reach: its weights are non-commercial. Sortformer is out of reach for
another reason: four speakers at most, and a meeting has six.
