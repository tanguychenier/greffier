# What the graphics card changes, measured

Measuring machine: Ryzen 7 3750H (4 cores, 8 threads), GTX 1660 Ti Max-Q
6 GB, driver 595.84, Ubuntu 24.04. Reference meeting: 40.7 s synthesised,
two voices. The machine was **loaded** during the measurements (load average
between 9 and 29: browser, OBS, containers); the processor figures therefore
vary from one to three times between runs, the card's hardly at all. Every
comparison was made twice in a row, under the same conditions.

## 1. Where the time went

| Item | Measure |
|---|---|
| pyannote segmentation alone, 5 windows | **0.35 s** |
| One 3 s TitaNet voiceprint on the processor | **0.47 to 1.10 s** |
| Complete `process()` of the segmentation | **43 to 95 s** |

Cutting into speaker turns is not expensive because of the segmentation: it
is expensive because it runs TitaNet, 101 MB, 25 million parameters, on
**every** excerpt. On the processor, that single model takes 1.9 to 2.8
times real time.

## 2. The same model on the card

Direct bench on TitaNet, fixed-size input, ten passes after three warm-up
passes:

| Excerpt length | Processor (4 threads) | Card |
|---|---|---|
| 1.5 s | 537 ms | **6.9 ms** |
| 3.0 s | 1,097 ms | **38.8 ms** |
| 6.0 s | 3,131 ms | **11.0 ms** |

## 3. End to end, with identical speaker turns

`auto` = the card when the driver answers.

| Item | Before (segmentation on the processor) | After (everything on the card) |
|---|---|---|
| Opening the transcription model | 12 to 19 s | 12 to 19 s |
| Transcription | 7.2 to 7.3 s | 7.2 to 9.0 s |
| **Speaker turns** | **30.2 to 38.9 s** | **6.2 to 8.9 s** |
| **Voiceprints** | **4.7 to 6.2 s** | **0.9 to 1.5 s** |
| **Total** | **58.7 to 62.7 s** | **32.5 to 33.8 s** |

The turns returned are **the same**, boundaries included: the card only
changes the time.

The assistant's voice follows: 2.43 s to speak a five-second remark on the
processor, **0.28 s** on the card.

Memory taken on the card: 383 MB for the segmentation, 1,905 MB for the
transcription model. Both fit together in 6 GB.

## 4. What did not work

**More threads.** `compute_threads()` already returns 4 on this machine,
the 4 physical cores. Measured from 1 to 8 threads on TitaNet: the noise of
the load exceeds the difference. Nothing to gain.

**Transcribing and segmenting at the same time.** Once both are on the
card, running them in two threads gives **0.92×**: 13.14 s instead of
12.12 s. They fight over the card and over feature extraction on the
processor. Abandoned.

**Aligning the ONNX Runtime versions.** See below: worse than the disease.

## 5. The trap: two ONNX Runtimes in one process

faster-whisper loads its own ONNX Runtime with its voice detector
(`vad_filter=True`), and the CUDA wheel of sherpa-onnx ships its own. The
two do not hold together:

| Order | Result |
|---|---|
| sherpa first, then faster-whisper | works |
| faster-whisper first, then sherpa on the **processor** | works |
| faster-whisper first, then sherpa on the **card** | `node_index < nodes_.size() was false` |
| versions brought closer (onnxruntime 1.27.0 against the embedded 1.27.1) | **segmentation fault** |

Whichever opens second binds to the other's symbols. Bringing the versions
closer repairs nothing: it replaces a corrupted graph with a killed
interpreter.

Hence the two rules in the code:

1. The composition root opens the card's session **before** building a
   transcriber: 1.09 s, and only the driver's context stays on the card
   (85 MB).
2. If the rival is there anyway, the segmentation falls back on the
   processor. Slow beats lost.

## 6. The wait after "Terminer"

Opening large-v3 takes longer than transcribing the meeting. Closing the
encoder cleanly takes up to fifteen seconds, and happens before. The two now
happen at the same time:

| | Measure |
|---|---|
| Without warm-up | 12 s of encoder + 21.98 s = **33.98 s** |
| With warm-up | 12 s of encoder + 12.06 s = **24.06 s** |

## 7. The models reopened every time

The card made visible what the slowness of the processor hid: several
models were **reopened at every use**.

| What reopened | When | Cost |
|---|---|---|
| The assistant's voice | at every question asked in preparation | 4.59 s |
| TitaNet voiceprints (101 MB) | at every click on "nommer", "séparer", "oublier" | 0.3 to 1.2 s |
| large-v3 transcription | at every processing | 12 to 19 s |

Three questions asked in a row to the assistant, before and after:

    question 1: 4.59 s     question 1: 4.59 s
    question 2: 4.6 s      question 2: 0.29 s
    question 3: 4.6 s      question 3: 0.31 s

The three models are now kept for the process, per file and per device. The
voice also opens while the person is speaking into the microphone or the
writer is thinking, so that even the first answer arrives spoken.

## 8. Replaying these measurements

The measuring scripts are not versioned: each holds in some twenty lines and
depends on a recording which, itself, cannot be. What they do:

- open TitaNet through `onnxruntime` alone, forcing `CPUExecutionProvider`
  then `CUDAExecutionProvider`, and time ten passes on a `(1, 80, N)` input;
- build an `OfflineSpeakerDiarization` with `provider="cpu"` then `"cuda"`
  on the same models and compare the turns returned;
- call `wiring._transcriber`, then `SherpaDiariser.segment`, then
  `TitaNetExtractor.extract_spans` on one file, timing each item.
