# The scenarios: what is proven, what is not

A tool that listens to meetings meets a finite number of situations, and
most of them have never been played. This document lists them all, says
which are covered and by what, and serves as a work plan. A situation not
listed here is a situation nobody has thought of: adding it is better than
discovering it in a sitting.

Three states: **covered** by a test that would fail if the behaviour
changed, **measured** without being held by a test, and **open**.

## The sound take and the room

| Situation | State | Where |
|---|---|---|
| Two distinct voices, video call | covered | `test_whole_chain` |
| Three voices around a table, one microphone | covered | `test_in_the_room` |
| System sound leaking into the microphone | covered | `test_in_the_room` |
| Microphone in the middle of the room, four people, room noise | measured | AMI corpus, 91.6 % accuracy |
| Somebody **arrives during** the meeting | open | |
| Somebody **leaves** before the end | open | |
| Somebody **changes seat** or moves away from the microphone | partly | levelling the excerpts neutralises it |
| Headset plugged in or out during the sitting | partly | the hardware event is tracked, the continuity of the voice is not |
| Long **overlapping speech**, two people together | open | |
| Long silence, then resumption | open | |
| Continuous background noise: ventilation, street, keyboard | open | |
| Somebody on a **phone's loudspeaker** on the table | open | |
| **Hybrid** meeting: people in the room, others online | open | |
| **Music or video** played during the meeting | open | |
| The same person **present and connected**: their voice arrives twice | open | |
| A meeting longer than the four-hour guard | open | |
| A thirty-second meeting | covered | the test set lasts 35 s, `test_whole_chain` |

## The language

| Situation | State | Where |
|---|---|---|
| Meeting in French | covered | the whole chain |
| Interface in English | covered | `test_wording_files`, `test_chosen_language` |
| Meeting **mixing two languages** | open | |
| Person with a **strong accent** | open | |
| Rare terms and acronyms | measured | 11 out of 15 without the prompt, 15 out of 15 with |
| Numbers, dates, amounts said aloud | open | |

## Who is who

| Situation | State | Where |
|---|---|---|
| Two first names said, two voices | covered | `test_whole_chain` |
| Somebody mentioned but absent | covered | `make_hard_cases`, case "absent" |
| First name called out with no answer | covered | `make_hard_cases`, case "sans-reponse" |
| A person from the bank absent from the meeting | covered | the expected people bound the bank |
| The bank recognises a voice from one meeting to the next | covered | `test_bank_across_meetings` |
| **Two people with the same first name** in the same meeting | open | |
| A name **corrected during** the meeting | partly | `test_live_with_assistant` |
| A **wrong voiceprint enters the bank**, and one has to recover | partly | `intruding_voiceprints` exists, the journey does not |
| A bank of **hundreds** of people | open | |
| Two voices joined by hand, to be **split again** | covered | `greffier voix --separer`, button in the Voices tab |

## What the assistant answers from

Played end to end against the real model behind Claude Code
(`test_context_scenarios`, skipped where `claude` is not signed in), through
the product's own path: the material the meeting hands her, her spoken
guidance, her answer.

| Situation | State | Where |
|---|---|---|
| A document handed over is used, and named | covered | "D'après le document budget, le lot 2 est fixé à quarante-deux mille euros hors taxes" |
| A registered source without a token: she says she has no access and asks for it | covered | "Je n'ai pas accès à la source GitLab, il manque le jeton pour le projet équipe outil. Il faut le déposer là où le fichier des sources l'indique" |
| The token pasted into the window, the source read and named | covered | `test_the_window_itself`, then "D'après GitLab, deux tickets sont ouverts sur le projet équipe outil : le numéro 12, facturation en double sur l'avoir" |
| A fact outside the meeting looked up on the web, the source named | covered | "D'après le site officiel de Python, la dernière version stable est actuellement la 3.14.7" |
| A Jira project read the same way | partly | the adapter and the material are covered by unit tests, the scenario is not played |
| Trello, Outlook, a shared drive | open | not registered kinds |
| She installs an access herself, with consent | open | she asks for the token; the gesture stays a person's |

## The project manager's day

The tool seen from the seat of somebody who runs the meeting rather than
records it, before, during and after. Every line either points at the test
that holds it, or says what is missing.

### Before

| Situation | State | Where |
|---|---|---|
| Say out loud what the meeting is about, and get the setting ready | covered | `test_prepare`, `test_preparation`, the Préparation tab |
| Hand over the documents (agenda, budget, last minutes) | covered | `test_the_window_itself` (a document kept for the meeting), `test_attachments_file` |
| Say who will be there, so that the bank looks only for them | covered | the expected people bound the bank, `test_process` |
| Teach the tool the acronyms and the names of the house | covered | `test_context_file`, `greffier contexte`, what a document teaches offered to the context |
| Read the agenda from the calendar | open | no calendar is read |
| Look something up before the meeting | covered | the Conversation tab with the web search, `test_context_scenarios` |

### During

| Situation | State | Where |
|---|---|---|
| Ask her a question by her name and get the answer out loud | covered and measured | `test_assistant_latency`, `measure_assistant.py`, 4.6 to 6.5 s on a small card |
| The question is asked while somebody was still talking | covered | half a question is held, `test_watch` |
| She answers from the documents, the company's tickets, the web, and names what she used | covered | `test_context_scenarios` |
| She says she has no access, and gets it without a terminal | covered | Réglages ▸ Sources d'entreprise, `test_the_window_itself` |
| She spots a decision, an action, a question left open | covered | `test_instructions`, `test_questions`, the Conversation badge |
| Somebody is named on the fly, and the live thread follows | covered | `test_live_with_assistant`, `test_follow` |
| The consent line is reminded once per session | covered | `test_consent` |
| She takes the floor of her own accord | partly | `initiative` exists, `test_take_part`; not measured on a real meeting |
| She is told to be quiet, and is, at once | covered | the two buttons, `test_watch` |

### After

| Situation | State | Where |
|---|---|---|
| The minutes, with who said what | covered | the whole chain, `test_whole_chain` |
| Name the voices, once, and be recognised next time | covered and measured | `test_bank_across_meetings`, `measure_bank.py` on SUMM-RE 032a → 032b |
| The tickets offered from the minutes | covered | `test_tickets`, `greffier tickets` |
| The tickets created on GitLab or Jira, one yes each | covered | `greffier tickets --creer`, `test_cli_after_the_meeting` |
| The minutes sent, after reading who gets them | covered | `greffier envoyer`, `test_email_smtp`, `test_email_outlook` |
| The board of subjects published to Miro | covered | `test_board_miro`, `greffier carte` |
| The transcript exported for a player or a spreadsheet | covered | `test_export`, the Meetings tab |
| A follow-up question on the minutes, days later | covered | the Conversation tab on a chosen meeting, `test_the_window_itself` |
| A meeting that was never processed, rebuilt from its thread | covered | `greffier recuperer`, `test_recover` |
| The recordings tidied by the retention rule | covered | `greffier ranger`, `test_tidy` |
| A comment left on an existing ticket after the meeting | open | `gitlab_api.comment` exists, no gesture calls it |
| A meeting held in Outlook or Teams, joined by the tool | open | the loopback carries the sound; nothing reads the invitation |

## What breaks

| Situation | State | Where |
|---|---|---|
| The writer fails, the transcript is kept | covered | `test_window`, resumed by "Rédiger" |
| No model installed | covered | the window says so and offers |
| The graphics card cannot compute | covered | `test_transcription_device` |
| Two ONNX engines in one process | covered | `test_cuda` |
| **Full disk** during the recording | covered | `test_space`, the watch warns once |
| The **microphone disappears** during the sitting | partly | hardware watch on macOS |
| The machine **goes to sleep** | open | |
| The **network drops** during the write-up | partly | the timeout exists, the journey does not |
| The application **stops** during the sitting | partly | `greffier recuperer` |
| The **models are deleted** between two meetings | open | |
| **Damaged** audio file | covered | `why_unreadable`, before the models open |
| **Clock change** during the meeting | open | |

## What the law asks

| Situation | State | Where |
|---|---|---|
| Say in the minutes what was announced to the attendees | covered | consent line |
| **Erase a person** from the bank and from every meeting | covered | `test_erase_person`, `greffier oublier-une-personne` |
| Erase a whole meeting | covered | `greffier oublier`, and "Supprimer" in the Meetings tab |

## What the tool should have

Both lines that stood here were done on 16/09: the live thread marks the
doubtful sentence « (?) » as it appears (`test_the_window_itself`), and a
first launch lists the three things to do in the Conversation tab and ticks
them as they get done (`test_the_window_itself`, `test_first_launch`).

## What has just arrived

- **One confidence per turn**, measured before being shown: the readable
  transcript marks "(?)" the passages the model did not hear well, the
  spreadsheet carries the figure, and the window says how many passages
  deserve a second listen. The threshold comes from
  `tools/measure_confidence.py`, see `docs/calibration.md`. Covered by
  `test_doubt`.
- **Exporting the transcript** as SRT, WebVTT or CSV, from the command line
  and from the window. The subtitles are cut like subtitles: two lines of
  forty-two characters at most, the speaker's name counted in the width of
  its line and written once per turn, the turn's length shared between its
  blocks. Covered by `test_export`.

## What was tried and taken back

**Attaching a scrap to its neighbours.** A scrap too short to carry a
voiceprint, framed on both sides by the same voice and less than two seconds
from each, almost surely belongs to it. The rule was written, wired and
measured on a real meeting through the table microphone:

| | Right | Wrong | No opinion |
|---|---|---|---|
| Without the rule | 91.6 % | 0.3 % | 8.1 % |
| With the rule | 91.8 % | **0.5 %** | 7.7 % |

Two tenths gained on one side, two tenths lost on the other: the exchange is
one for one between "I do not know" and "I am wrong". The second costs more
than the first, since it gives somebody's words to somebody else and nobody
sees it. The rule was therefore taken back.
