# A real corpus in French

On a synthesised meeting, the sixteen decoding combinations give the same
1.75 % word error rate (`what-is-left.md`, 2026-09-12): the synthetic
carries neither overlap, nor accent, nor distance to the microphone, the
three causes of the complaint "the words shown were not the ones said in the
meeting". Telling settings apart takes real speech, with a reference written
by people.

## The candidates, checked on 2026-09-15

Four criteria: French, several speakers in the same room, a reference text
with the turns, a licence that allows the use. The audio never enters the
repository: a script fetches it from its producer.

| Corpus | What it is | Reference | Licence | Verdict |
|---|---|---|---|---|
| **SUMM-RE** (LINAGORA / LPL Aix-Marseille, Hugging Face `linagora/SUMM-RE`) | 283 meeting-style conversations of 20 min, 3 to 4 people, spontaneous, scenario-driven (reporting, decision, planning); one microphone and one track per person; 25 meetings of the `dev` split recorded **in person** at the H2C2 studio and 3 at the LPL | Manual transcription of the `dev` and `test` splits, word-aligned, per speaker; the card itself says speaker separation is evaluated by mixing the tracks | CC BY-SA 4.0 | **Kept.** Covers overlap and accent, not distance to the microphone: the tracks are close-talk, the mix has no room acoustics |
| **Committee hearings of the Assemblée nationale** (`videos.assemblee-nationale.fr`) | One room, table microphones, a chair, members at varying distances, one or more witnesses; real interruptions and overlaps | The minutes naming every speaker, published within days; **complete but edited**: hesitations removed, syntax straightened | Video download open on the portal, video licence unstated; minutes of the sittings under the Licence Ouverte on `data.assemblee-nationale.fr`. Use here: local measurement, no redistribution | **Kept**, with a measure to match: an edited text forbids a raw error rate; terms found and speaker attribution are measured, and the word error rate on a five-minute passage checked by hand |
| **CEFC / ORFEO** (ORTOLANG) | 450 h aggregated from fourteen corpora: interviews, two-party conversations, narratives, service interactions; few meetings of more than two | Aligned | CC BY-NC-SA 3.0 FR | Refused: almost no meetings, and the non-commercial licence brings nothing SUMM-RE does not give already |
| **ESLO 1 and 2** (ORTOLANG) | Sociolinguistic interviews in Orléans, two people, often in the street | Aligned | CC BY 4.0 | Refused: interviews, not meetings |
| **TCOF** (ORTOLANG) | Adult-adult interactions including "work meetings", single recorder | Aligned | CC BY-NC-SA 2.0 | In reserve: if the Assemblée is not enough for room acoustics |
| **Conférences Pierre Mendès France** (data.gouv.fr, Bercy) | 300 h of conferences with questions from the floor, MP3 and XML | Format and fidelity not described on the card | Licence Ouverte 2.0 | In reserve: one main speaker, not a meeting |
| **VoxPopuli, Europarl-ST** | Speeches at the European Parliament, one speaker at a time | Yes | CC0 / CC BY-NC | Refused: speeches, not exchanges |
| **ESTER, ETAPE, MEDIA** (ELRA) | Radio, television, telephone dialogues | Yes | Paid | Refused: paid, and not meetings |
| **AMI** | Meetings in English, already used (91.6 % attribution) | Yes | CC BY 4.0 | Kept for speaker separation, useless for French |

## What is kept, and why these two

SUMM-RE brings what no other gives: a **word-for-word** reference, per
speaker, on French people who really cut each other off. The Assemblée
brings what SUMM-RE lacks: **a room**, people far from the microphone, and
more speakers than a business meeting ever has. Between them they cover the
three causes of the complaint.

## The recordings

`python3 tools/fetch_corpus.py` puts them in `corpus/` under the data folder
(`~/.local/share/greffier/corpus` on Linux), each with its reference
`*.reference.json`: the source, the licence, the speakers and the turns.

| File | What | Length | Speakers | What it brings |
|---|---|---|---|---|
| `summre-032a_EARH.wav` | SUMM-RE, reporting meeting, H2C2 studio, four tracks mixed into 16 kHz mono | 19.7 min, 17.5 min of speech, 391 turns | 4 | Word-for-word reference; 1.4 min of overlapping speech |
| `summre-036c_EAPH.wav` | SUMM-RE, planning meeting, same studio | 26.8 min, 25.8 min of speech, 812 turns | 4 | Word-for-word reference; **5.1 min of overlapping speech**, a fifth of the time |
| `assemblee-2026-07-22.wav` | Hearing of "Les Oubliés de la République", committee of inquiry on the rise of poverty; the video starts a quarter of an hour before the opening, the tool cuts that silence and keeps the first 40 minutes of the sitting | 40 min out of 2 h 24 | 8 named in the minutes (chair, rapporteur, one member, five witnesses) | A room, table microphones, people at varying distances; 57 edited turns, 15,600 words |

Checked by the model's ear, not only by the figure: the first 25 seconds of
the Assemblée file transcribe to "Mes chers collègues, [je] vous souhaite la
bienvenue pour cette dernière audition avant la pause estivale", the first
turn of the minutes; at 20 minutes a witness introduces himself. The minutes
in fact dropped "pour cette dernière audition avant la pause estivale": that
kind of cut is what forbids a raw error rate on this text.

What the script does not do: it keeps neither the video (1.2 GB, deleted
after extraction) nor the Hugging Face parquet files (one gigabyte, in the
`huggingface_hub` cache, to be deleted by hand). None of these files enters
the repository.

## The measurement, default settings (2026-09-15)

`python3 tools/measure_corpus.py`, the installed chain as it is: `large-v3`
on the card, no vocabulary prompt, no attendee count declared. Three
figures per recording, defined in the tool and held by
`tests/test_measure_corpus.py`:

- **the word error rate**, both texts read the same way (lower case, no
  punctuation, no "euh"), edit distance on the words;
- **the rare terms found**: the words the reference uses once and that are
  at least seven letters long, the ones a model replaces with a commoner
  word;
- **the attribution**: each voice returned is taken to be the person it
  carries most often, then each sentence is *right*, *wrong*, or *no
  opinion* when it received no voice. The last two are not the same fault:
  a wrong name in the minutes is worse than a blank.

| | Word error rate | Rare terms | Right | Wrong | No opinion | Voices returned / people |
|---|---|---|---|---|---|---|
| Assemblée, 40 min | 47.1 % *(edited text)* | 433 / 578 (75 %) | **96.7 %** | 2.9 % | 0.4 % | 5 / 7, one scrap |
| SUMM-RE 032a, 19.7 min | **21.6 %** | 224 / 254 (88 %) | **89.0 %** | 2.8 % | 8.2 % | 4 / 4 |
| SUMM-RE 036c, 26.8 min | 33.0 % | 169 / 227 (74 %) | **64.1 %** | **23.9 %** | 12.1 % | **2 / 4**, ten scraps |

### What the figures say

**Words are lost in the overlap, not in the vocabulary.** On 032a, the
21.6 % break down into 12.1 % omissions, 4.4 % substitutions and 5.2 %
insertions. The omissions are the short words thrown in while somebody else
is speaking: "ouais" (17 times), "ok" (14), "ben" (11), "non" (9). Part of
the substitutions are none: "vingt" written "20", "etcetera" written "etc",
"y'a" written "il y a". The insertions are led by the negation "ne" (15
times), which people do not pronounce and the model writes back. On 036c,
where a fifth of the time is spoken by two people, omissions rise to 19.3 %.

**The Assemblée is not measured in word error rate.** Against the 4,700
words of the minutes covered by the 40 minutes, 24 % of the words heard are
not in them ("et", "donc", "je", "que": the published text tightens) and the
minutes write "nous" where the witness said "on". The figure measures the
editing. What the hearing brings is the room: 96.7 % right attribution with
table microphones, two voices for the chair (2 and 19), and Mme Maurer fused
into M. Abdelatif's voice (11 sentences out of 92, the 2.9 % wrong). The two
remaining "people" of the 7 have one sentence each.

**The defect is 036c: four people returned as two voices.** Voice 0 carries
093 and 099 (437 and 103 sentences), voice 26 carries 092 and 091 (84 and
72). These are not split voices, these are people **fused in pairs**, with
ten one-sentence scraps around. The minutes would announce two attendees
where there are four, and a quarter of the sentences would carry the wrong
name. The same chain on 032a, same studio, same set-up, returns 4 voices for
4 people at 89 %. The difference between the two meetings: 1.4 min of
overlapping speech on one side, 5.1 on the other, and closer pairs of
voices. That is the case the synthetic never produced, and the one to bring
down first.

### What it changes in the plan

- The next box (replaying the sixteen combinations and the prompt) is played
  on 036c and 032a, where the reference is word for word; the Assemblée only
  serves attribution.
- Omissions in the overlap are not fixed by a decoding setting: it is a
  separation problem, not a transcription one.
- The 12 voices of 036c put phase 5 (adopting the small aggregates at the
  live threshold) in front of a real meeting, with a figure to beat: 64.1 %.

## The sixteen decoding combinations, on real speech (2026-09-15)

`python3 tools/measure_decoding.py`: the same audio preparation as the
chain, `large-v3` on the card, the sixteen combinations of `beam_size` (5 or
1), `vad_filter`, `condition_on_previous_text` and `temperature`
(faster-whisper's fallback ladder, or 0). On the synthetic they all gave
1.75 %; on real speech they go **from 21.5 % to 409 %**.

| Combination | 032a (19.7 min) | 036c (26.8 min) | Time on 032a |
|---|---|---|---|
| **beam 5, vad, cond, ladder** *(the product)* | 22.1 % | **29.8 %** | 373 s |
| beam 5, no vad, cond, ladder | **21.5 %** | 30.1 % | 292 s |
| beam 1, no vad, cond, ladder | 24.2 % | 31.4 % | 198 s |
| beam 1, vad, cond, ladder | 24.4 % | 31.7 % | 239 s |
| beam 1, no vad, no cond (ladder or 0) | 22.9 % | 33.3 % | 162 s |
| beam 5, vad, no cond (ladder or 0) | 24.0 % | 34.0 % | 225 s |
| beam 5, no vad, no cond (ladder or 0) | 24.4 % | 34.3 % | 225 s |
| beam 1, vad, no cond (ladder or 0) | 24.5 % | 34.5 % | 158 s |
| beam 5, vad, cond, **temperature 0** | 22.1 % | **43.6 %** | 322 s |
| beam 5, no vad, cond, **temperature 0** | 21.5 % | **85.3 %** | 329 s |
| beam 1, vad, cond, **temperature 0** | 31.3 % | **80.4 %** | 173 s |
| beam 1, no vad, cond, **temperature 0** | **409 %** (17,642 words for 4,103) | **88.9 %** | 784 s |

### What moves a figure, and what does not

- **The product's setting is the right one.** Best on 036c, 0.6 point from
  the best on 032a. Nothing to change.
- **The danger zone is sharp**: `condition_on_previous_text` **without** the
  temperature ladder. The model starts looping: 17,642 words transcribed for
  4,103 spoken on 032a, and four times out of four beyond 43 % on 036c. The
  fallback ladder is what saves the conditioning; cutting it is the only way
  to break the transcription with a setting.
- **Without conditioning nothing ever loops**, at a cost of 2 to 4 points.
  That is the safe fallback if a loop is ever seen in a meeting.
- **The beam** is worth 1 to 2 points and costs 1.5 to 2 times the time.
- **The voice filter** plays half a point, either way.
- **What no setting recovers**: on 036c the best stays at 29.8 %, and the
  omissions (19.3 % at the product's setting) are the words said while
  somebody else is speaking. That is not a decoding problem.

### The prompt, with no vocabulary to give it

The product only sends a prompt when a vocabulary is configured: "Réunion de
travail. Vocabulaire : …". Measured alone, the leading sentence with no term
behind it **costs**: 24.9 % instead of 22.1 % on 032a, 30.5 % instead of
29.8 % on 036c, and two to five rare terms fewer. The gain measured on 12/09
(11 then 15 terms out of 15) therefore comes from the terms, not from the
sentence in front of them. Nothing to change as long as the prompt only
exists with terms; if it is ever sent empty, this figure says not to.

## The stitching, pass by pass (2026-09-15)

`python3 tools/measure_stitching.py`: the segmenter's own groups and their
voiceprints computed once, then every strategy scored in a second against
the reference timings, on the turns and weighted by speaking time. The
question was which of the three passes fused four people into two on 036c,
and what the live threshold (0.50) would have done instead.

| Strategy | 032a: voices / right / wrong | 036c: voices / right / wrong |
|---|---|---|
| segmenter alone | 13 (+57 scraps) / 95.6 % / 4.4 % | 26 (+155 scraps) / 96.8 % / 3.2 % |
| pairs at 0.75 | 5 / 93.8 % / 6.2 % | **4** / 93.5 % / 6.5 % |
| pairs at 0.65, 0.55 or 0.50 *(the live threshold)* | 4 / 93.3 % / 6.7 % | **2** / 72.5 % / 27.5 % |
| pairs + adoption (0.45, 0.55 or 0.65) | 4 / 93.3 % / 6.7 % | **4** / 93.5 % / 6.5 % |
| pairs + adoption + consolidation at **0.70** *(the product until today)* | 4 / 93.3 % / 6.7 % | **2** / 72.2 % / 27.8 % |
| pairs + adoption + consolidation at 0.80 or 0.90 | 4 / 93.3 % / 6.7 % | **4** / 93.5 % / 6.5 % |

### What it says

- **The consolidation pass did it, not the pairs and not the adoption.**
  After pairs and adoption, 036c holds exactly four established groups, one
  per person, at 93.5 % right. Consolidation at 0.70 then joined 093 with
  099 at 0.717 and 091 with 092 at 0.704: two different people each time.
- **The live threshold is the wrong lead.** Lowering the pairs pass to 0.50
  fuses the same two pairs a step earlier. The live thread does better on
  the meeting of 2026-09-10 for another reason, worth its own measurement,
  not by its threshold.
- **Where 0.80 comes from.** At the scale of established groups, on both
  meetings: the same person cut in two halves scores **0.932 at the lowest**
  (0.946 on 036c), two different people **0.730 at the highest** (0.581 on
  032a). Slices of forty seconds against the rest of the same person: median
  0.94 to 0.97, one outlier at 0.711. 0.70 sat inside the different-people
  range on this corpus; 0.80 sits between the two with 0.07 below and 0.13
  above. The AMI figure that set 0.70 (different people never over 0.652)
  held for English meetings through a far-field microphone; French speakers
  close to their microphone come out more alike.
- **The cost of raising it**: a person whose two halves score under 0.80
  stays two attendees. Not seen on this corpus (minimum 0.932); the outlier
  at 0.711 is a forty-second slice, which adoption handles before
  consolidation is reached.

`CONSOLIDATION_THRESHOLD` goes from 0.70 to 0.80. The three recordings are
measured again through the whole chain below.

## The whole chain again, consolidation at 0.80 (2026-09-16)

`python3 tools/measure_corpus.py --again`, one recording at a time, same
default settings, `CONSOLIDATION_THRESHOLD` at 0.80:

| | Word error rate | Rare terms | Right | Wrong | No opinion | Voices / people |
|---|---|---|---|---|---|---|
| Assemblée, 40 min | 40.1 % *(edited text)* | 486 / 578 | **96.9 %** | 3.1 % | 0.0 % | 5 / 7, one scrap |
| SUMM-RE 032a | 24.5 % | 220 / 254 | 87.5 % | 2.3 % | 10.2 % | **4 / 4** |
| SUMM-RE 036c | 28.4 % | 174 / 227 | **71.9 %** | **9.0 %** | 19.1 % | **4 / 4**, sixteen scraps |

036c returns its four people: wrong attributions go from 23.9 % to 9.0 %,
and each of the four voices carries one person (235 of 266 sentences, 73 of
81, 59 of 70, 40 of 43). The share of *no opinion* rises to 19.1 %: 146
short sentences, median 1.1 s, the backchannels thrown in while somebody
else speaks, attached to no turn at all. That is the overlap again, not the
stitching.

**A caveat the two runs make visible.** The same setting on the same file
does not give the same transcription twice: 032a came back at 24.5 % where
the first run gave 21.6 %, 036c with 645 sentences where the first run had
917. The temperature ladder samples where the model is unsure, so the
sentence-level figures move by a few points from one run to the next. The
comparison that settles a threshold is the turn-level one of
`measure_stitching.py`, computed once from a cached segmentation, where
036c goes from 72.2 % to 93.5 % right with nothing else changed.

## The assistant's speed, from the end of the question to her first word (2026-09-16)

Asked from use: she took seconds to answer, and it felt long. Measured on a
synthesised meeting that asks her three questions and leaves her twelve
seconds after each (`tools/measure_assistant.py`), through the chain a
meeting runs: the pass that spots her name, the model that phrases the
answer, the voice that renders it, the loudspeaker replaced by a clock. Three
figures per question, all counted from the end of the question: *spotted*
(her name heard), *answered* (the model's text back), *ready* (the first
sentence rendered, the moment the room would hear her). Two runs each.

Where the seconds went, measured one piece at a time:

| Piece | Before | After | What changed |
|---|---|---|---|
| The model, one question | `claude -p` cold: 4.6 s haiku, 5.0 sonnet, 6.2 opus | 1.4 to 2.4 s | One process kept open for the meeting (`brain_claude`), fed one message after another; the guidance as its system prompt (first token 0.7 s instead of 2.7); sonnet rather than opus for what is spoken |
| The listening pass | in the loop, after the slice: every 4 s at best, never while a slice was transcribed | its own thread, run the moment the room goes quiet | `SpeechEnd` on the levels of the file being written; the clock as fallback, and no pass while nobody has spoken |
| The live model, on this card | large-v3: 12.1 s per minute, 1.95 s per pass | large-v3-turbo: 3.7 s per minute, 1.3 s per pass | Turbo where the card takes the large model; the installer fetches it |
| The voice, first answer | 5 to 6 s to open | opened before the first word | Warmed up at the start of the meeting, with the live model |
| A question cut in half | answered as heard | held for the next pass | A call with no full stop waits once; the same words again go through |

Which small model would hear her name: base heard it 4 times out of 8 on
the synthesised voices, small 4 out of 8, large-v3-turbo 8 out of 8. The
pass keeps the turbo model.

End to end, on this machine (CUDA, 6 GB, live thread on), the same file
before and after, two runs each:

| | Question 1 | Question 2 | Question 3 |
|---|---|---|---|
| Before, spotted / answered / ready | 5.0 / 8.6 / **8.9** s and 3.9 / 11.5 / **11.8** s | 3.5 / 8.8 / **9.3** s and 3.8 / 7.7 / **8.0** s | 6.2 / 9.8 / **10.0** s and 4.4 / 8.5 / **8.9** s |
| After | 0.0 / 1.4 / **3.0** s and 0.0 / 2.6 / **2.8** s | 1.7 / 3.3 / **3.5** s and 1.9 / 5.8 / **6.5** s | 2.9 / 5.1 / **5.6** s and 3.6 / 10.7 / **11.0** s |

From 9.5 s on average to 5.4 s, and to **3 s on the first question** of each
run: the room's half second of quiet, the pass, the model, the voice. The
second run's third question is the model taking seven seconds to answer
where it takes two elsewhere, which the bench shows as it is: the wire is
the account's, and its speed is not the tool's to promise. The question
timeline ends where the synthesised file ends, half a second after the
voice stops, which is why a name can be *spotted* at 0.0 s.

What is left, in order of size: the model's share (1.4 to 2.6 s when it
answers at its usual pace), then the pass (1.3 s on this card for eight
seconds of audio, 0.8 s on the MacBook the tool runs on), then the half
second the room has to keep quiet before anyone can tell the question is
over.

### The answer spoken as it comes, and two things the bench caught (2026-09-16, later)

The session now asks Claude Code for the partial messages and hands each
finished sentence to the voice while the model writes the next one.
Measured on the wire with sonnet, cold, three sentences: the first was
whole at 2.6 s where the answer came back at 3.7. On the bench the answers
are one sentence long, and one sentence is whole only when the answer is:
*ready* stays 0.3 to 0.5 s after *answered*, the time the voice takes to
render it. The gain is on answers of two sentences or more, which the
guidance allows and the bench does not ask for.

Two defects the same bench showed, fixed before the run below:

- **A breath in the middle of a question was taken for its end.** The
  levels prompted a pass 0.4 s before « Lucie, combien d'anomalies
  bloquantes restent à valider ? » was over; the pass heard the question
  up to « restent », the model answered « RIEN » to half a question, and
  the slice answered the whole one ten seconds later. A prompted pass now
  hands nothing over when the room went on talking while it transcribed.
- **The words just before the call now travel with it.** The thread the
  assistant answers from runs a slice behind, and with the slice waiting
  for a quiet moment it can run three seconds further behind: she answered
  « ce point n'a pas été mentionné dans la réunion » to a question about
  the sentence said right before it. The pass that hears the call heard
  those words too; they go to the model with the question.

The bench again, the same file, two runs, slices cut on silence, the
answer spoken as it comes:

| | Question 1 | Question 2 | Question 3 |
|---|---|---|---|
| Spotted / answered / ready | 4.1 / 5.8 / **6.2** s and 2.9 / 4.7 / **5.0** s | 4.0 / 5.4 / **5.7** s and 2.0 / 3.6 / **4.0** s | 1.9 / 3.5 / **4.1** s and 2.1 / 3.9 / **4.2** s |

4.9 s on average, against 5.4 on the previous bench and 9.5 before the
day's work; what moves between two runs is the pass and the model, not
the tool. The second question of the first run is the one answered « ce
point n'a pas été mentionné », measured before the words just before the
call travelled with it.

A caveat on the day's benches, and the reason there are two "after"
rows in `assistant.json`: the first "after" was measured with the large
model still on the live thread, `downloaded` having looked for the turbo
model under the wrong repository name and said no. The figures above are
the ones with the turbo model really on.

## The live words against the reference (2026-09-16)

`tools/measure_live.py` replays SUMM-RE 032a slice by slice through
`Watcher.transcription_turn` and the real live thread, driving the clock
itself, and holds the words the thread shows against the reference. The
final transcription of the same file reads at **24.5 %** of errors and
220 rare terms out of 254 (large-v3, the full recording at once). The
live thread can only do worse; the question was by how much, and what
moves the figure. Seconds per slice are wall time on this card, live
thread included (voiceprints, levelling).

| Live model | Period | Context before the slice | Levelled | Word error rate | Rare terms | Seconds per slice |
|---|---|---|---|---|---|---|
| large-v3 | 10 s | 50 s | yes | 31.2 % | 205 | 17.0 |
| large-v3 | 10 s | 20 s | yes | **29.6 %** | 203 | 9.4 |
| large-v3 | 10 s | none | yes | 32.5 % | 203 | 4.1 |
| large-v3-turbo | 10 s | 50 s | yes | **43.3 %** | 161 | 10.9 |
| large-v3-turbo | 10 s | 20 s | yes | 32.0 % | 205 | 6.6 |
| large-v3-turbo | 10 s | none | yes | 31.5 % | 205 | **3.0** |
| large-v3-turbo | 10 s | 20 s | no | 32.7 % | 202 | 3.9 |
| large-v3-turbo | **5 s** | 20 s | yes | **56.5 %** | 126 | 4.7 |
| large-v3-turbo | 10 s, **cut on silence** | 20 s | yes | **28.8 %** | **221** | 7.0 |
| large-v3-turbo | 10 s, cut on silence | none | yes | 29.3 % | 205 | 3.9 |

What it says, the same file giving figures two or three points apart from
one run to the next (the temperature ladder samples where the model is
unsure):

- **The context before the slice buys nothing** on the words: 29.6 to 32.5
  for large-v3 across none, twenty and fifty seconds, 31.5 to 32.0 for the
  turbo model across none and twenty, the rare terms unchanged. It costs
  everything on the card: a slice of ten seconds with fifty of context is
  a minute of audio, 17 s on this card with the large model. **Fifty
  seconds hurt the turbo model outright**: 43.3 %, a third of the rare
  terms gone, the model losing its footing on a long window.
- **The period must not go under ten seconds**: at five, every sentence is
  cut in half at a boundary, heard in two pieces that do not add up, and
  half the rare terms are lost.
- **The turbo model reads two to three points worse than large-v3** on the
  same slices, at less than half the cost; the levelling costs a third of
  the slice time for a point that is inside the noise on a studio
  recording, and stays for the rooms it was measured on.
- **Cutting the slice at a quiet moment rather than on the clock buys
  three points**, and sixteen rare terms with the context: a slice past
  its ten seconds waits while somebody talks, up to three seconds, and
  the sentence under way is heard whole instead of in two pieces that do
  not add up. 104 slices instead of 119 on the same file, so the card
  spends less too. The turbo model with twenty seconds of context and the
  cut on silence reads at 28.8 %, where large-v3 on the clock read at
  29.6: the live thread is now within four points of the final
  transcription. It is what the product does (`SLICE_SLACK_S`).

What follows: `CONTEXT_S` goes from 50 to 20, not to none. The words read
alike either way; twenty keeps what a real meeting showed on 2026-09-09
for a proper name ("sur la ZIS" with fifteen seconds of window, "sur Asis"
with thirty, "sur Oasis" with sixty), which this corpus, a studio
conversation with few names of its own, cannot measure. The card spends
half of what it spent, and every second the card is not on a slice is a
second the assistant's name is heard sooner.

## The same four people, one meeting later (2026-09-16)

The question from use: does the tool keep somebody's voice, so that a
person named once is named by the tool the next time, whatever their tone
that day? SUMM-RE 032a and 032b are the same four people, a reporting
meeting and a decision meeting of the same series. `tools/measure_bank.py`
names the four voices of 032a after the reference, through the product's
own gesture (`Naming`, the one behind « greffier nommer »), then puts 032b
through the chain with that bank and through the live thread with it, and
checks every sentence the reference attributes: named right, named wrong,
left to nobody. The names are the reference's people, given first names
for the bank.

| 032b, 419 to 448 sentences judged | Right | Wrong | Nobody |
|---|---|---|---|
| After the meeting, the chain and the bank | **65.6 %** (275) | **6.7 %** (28) | 27.7 % (116) |
| Live thread, one voice per slice (before) | 71.4 % (320) | **28.3 %** (127) | 0.2 % (1) |
| Live thread, the slice cut at the changes of speaker, a sentence given from 80 % of its time | 74.5 % (333) | 12.3 % (55) | 13.2 % (59) |
| … and the scraps under the short threshold with the others | 75.4 % (337) | 11.0 % (49) | 13.6 % (61) |
| … a sentence given from 70 % of its time | 76.1 % (340) | 9.6 % (43) | 14.3 % (64) |
| … from 60 % | 76.3 % (341) | 8.5 % (38) | 15.2 % (68) |
| … **from half of it** (kept) | **80.3 %** (359) | **8.3 %** (37) | 11.4 % (51) |
| Live thread again, the transcriber in the loop, with all of the above | **82.1 %** (368) | **8.7 %** (39) | 9.2 % (41) |

Per person, after the meeting: Alice 88 right, 21 wrong, 56 to nobody out
of 165; Bruno 67 / 3 / 17 out of 87; Chloé 105 / 3 / 32 out of 140;
Diane 15 / 1 / 11 out of 27. Live, the slice cut, from half: Alice 102 /
21 / 19 out of 142; Bruno 117 / 3 / 5 out of 125; Chloé 121 / 12 / 17 out
of 150; Diane 19 / 1 / 10 out of 30. The replay is exact: the same
setting run twice gives the same thread to the byte, so a point between
two rows is the setting, not the dice. The last row is the live thread
run again in full, words transcribed on the card and slices cut: what the
replay promised, with the transcriber back in the loop.

What it says:

- **The bank recognises the same person a meeting later, every time.**
  After the meeting the chain finds four voices and the bank puts the four
  right names on them; live, the thread founds four voices and the bank
  names them right too, Chloé on the first sentence, Diane at 56 s, Bruno
  at 78 s, Alice at 161 s. Not one name is wrong at the end. What is wrong
  is the sentence under the name. One thing to know: in the full run, the
  voice that ends up as Alice was called « Diane ? » from 56 s to 161 s,
  named on six seconds of material and renamed once there was more; the
  question mark next to a name from a print is there for that.
- **After the meeting, a sentence in four is left to nobody**, by the
  rule of the minutes (`attribution.MINIMUM_SHARE`): a sentence whose time
  is not held at 80 % by one speaker turn goes to no one rather than to
  the most talkative. On a lively meeting where the four cut into each
  other, that is a quarter of the sentences, and 7 % still land on the
  wrong person, the boundaries of the transcriber not being the
  segmenter's. Alice, who carries 40 % of the sentences and changes tone,
  is held as one voice: 88 of her sentences on it, two scraps of a second
  each, and the 21 wrong ones on the three others' voices, not on a second
  Alice.
- **Live, the slice was one block.** The thread took one print per slice
  for everything that did not come from the microphone, and gave the ten
  seconds to whoever that print resembled: **28 % of the sentences under
  the wrong name**, and everybody named, since nothing was ever left out.
  A wrong name on screen costs more than no name.
- **The slice cut at the changes of speaker** brings the wrong ones from
  127 to 37. The segmentation model the chain uses is run on the slice
  alone, on the processor, in windows of ten seconds (0.14 s a window under
  load; the same audio read as one fifteen-second piece cost twelve
  seconds, the engine joining its windows with the voiceprint model). The
  labels hold inside the window only; the sentences are grouped by turn
  with the rule of the minutes, one print per group read where that
  speaker talks, and the thread joins the groups to its voices by print as
  it always did. Two more rules came out of the replay: a scrap under two
  seconds used to join the nearest voice whatever the likeness, and now
  joins it from the threshold measured for short material (0.45), or goes
  with the others; and the catch-all of those scraps must never take a
  print, since the bank then named the mixture of four people (eighty
  sentences under one name, in the run that showed it).
- **The share a turn must hold of a sentence is not the minutes' 80 %.**
  In the minutes the share decides the name, and a straddling sentence
  goes to nobody. Live, the share only groups the sentences whose audio
  makes one print, and the print decides the voice: the lower the share,
  the longer the groups, the better the prints, and the fewer sentences
  standing alone on a print of mixed audio. From 80 % down to half, the
  wrong ones go from 49 to 37 and the right ones from 337 to 359, every
  step in the same direction. `LIVE_MINIMUM_SHARE` is 0.5.
- **What is left wrong is short**: 25 of the 37 sentences last under two
  seconds, « Après Noël » said by two people in the same breath, « Arrête »,
  « Vendredi ! ». The rest sit in the exchanges where the four talk over
  one another, where the reference itself gives one sentence to one
  person.

The replay is `tools/measure_bank.py --replay`, through
`tools/replay_follower.py`: the live thread is fed the very words it
showed last time, slice by slice, without the transcriber, so a change to
who-said-what is measured in four minutes on the processor, the card left
to the words.
