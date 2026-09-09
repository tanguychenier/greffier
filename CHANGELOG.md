# Journal des modifications

Engendré depuis les messages de commit (convention Angular) :

    python3 outils/journal_des_modifications.py > CHANGELOG.md

## Nouveautés

- **voices** — replay the stitching without transcribing an hour again (`3a2e367`)
- **assistant** — let it raise a point, and mostly decide not to (`d99ce6f`)
- **assistant** — download its voice, and settle its name in the window (`9e8e52e`)
- **assistant** — give it a voice, a name, and the sense to keep quiet (`8051d8b`)
- **conversation** — teach it and feed it documents while the meeting runs (`c2252e8`)
- **sources** — read and write a registered GitLab or Jira, never beyond it (`e5e2336`)
- **depot** — drop audio, video or documents and get a proposed filing (`f7e7645`)
- **contexte** — teach it in a sentence, and confirm before writing (`a5d7995`)
- **consentement** — say in the report what the participants were told (`558bc94`)
- **carte** — stop the duplicates, mark what was decided, read what others add (`bedc063`)
- **niveau** — judge speech level, not silence, and say it during the meeting (`1c6faf8`)
- **recuperer** — rebuild a meeting from the live thread, and disarm --quand-meme (`af909c7`)
- **sauvegarde** — copy the work, since a lost disk took everything (`7316f63`)
- **calibrage** — measure the threshold across two sittings, not within one (`45fea5b`)
- **carte** — build a subject's map from a meeting, and publish it (`362c0ff`)
- **carte** — publish a subject map to Miro as native objects (`2f1fb31`)
- **carte** — the rules for a subject map that a meeting completes (`96bbe7c`)
- **maj** — install an update in one click, without losing anything (`b8892cf`)
- **retention** — keep recordings under an explicit rule, not a growing folder (`76e3c8c`)
- **conversation** — keep the conversation, and prove an update loses nothing (`5174a98`)
- **conversation** — let the assistant search, and never the report writer (`2d4ef14`)
- **version** — know which version is running, and whether a newer one exists (`2192b4c`)
- **fenetre** — make a failed report recoverable in one click (`db5a8ff`)
- **conversation** — queue the tool's questions, and count them on the tab (`d44899a`)
- **questions** — decide what the tool may legitimately ask about (`1d0c07e`)
- **conversation** — answer from the live thread while the meeting runs (`6ff84ef`)
- **reunions** — let the meeting name itself from its report (`4ac8a33`)
- **contexte** — tell the tool what a model cannot guess (`dc19391`)
- **reunions** — name a meeting, and forget one for good (`42a397f`)
- **installation** — write the language the machine announces, not "fr" (`3fe255c`)
- **langue** — ask for the language at install, and let the report follow it (`77dda08`)
- **domaine** — make the language a domain value instead of an assumption (`9a27192`)
- **transcription** — make the graphics card usable on Linux (`c3e5dc9`)
- Greffier, a local-first meeting assistant (`d0d8c8a`)

## Corrections

- **linux** — stop taking a directory for a working environment (`b5b9706`)
- **bank** — repair a bank at the grain that matters, the print (`55d9c4d`)
- **update** — make the update button able to work at all (`b72b4c4`)
- **minutes** — count the people present, and notice a writing left undone (`18a728e`)
- **names** — make naming a voice reversible, and stop it poisoning the bank (`c669188`)
- **voices** — stitch fragments onto the voices that carry the meeting (`3194bfb`)
- **direct** — give the model the minute before the slice, so the word is right (`ace8129`)
- **direct** — a term learned mid-meeting serves the next sentence (`f53c3b7`)
- **reglages** — say what the button updates, and reread the account on return (`1eee477`)
- **empreintes** — lower the recognition threshold to 0.45, measured (`af556b6`)
- **micro** — prefer a headset that hears anything, not the loudest one (`01bb710`)
- **fenetre** — make the action bar a proper grid, evenly spread (`fed0efa`)
- **fenetre** — let the action bar wrap, and give the tool a way to see it (`76aceec`)
- **carte** — complete a map instead of doubling it at every pass (`a18d0af`)
- **fenetre** — keep the startup notice out of a meeting's conversation (`0eb47be`)
- **journal** — write the session start, so the log says something at all (`9ca79cf`)
- **veille** — say it while the meeting is running when nothing is recorded (`cf04adc`)
- **compte-rendu** — report the clock times the recording kept (`0e3e0cd`)
- **depot** — order meetings by when they were held (`75155c9`)
- **traiter** — keep the meeting before writing the report (`6213ad9`)
- **fichiers** — stop collapsing non-Latin names to the same identifier (`36cd9b3`)
- **traiter** — keep the meeting when no report is written (`9378da5`)
- **diagnostic** — judge sound capture on the server, not on pactl (`0f60c78`)
- **interface** — size fonts in pixels and name families Tk guarantees (`abaf228`)
- **transcription** — fall back to the processor when the card cannot compute (`08a3af9`)

## Performance

- **locuteurs** — give the models half the cores instead of one (`6f6029e`)

## Documentation

- **sauvegarde** — a synchronised folder sends the data to its host (`6c714d4`)
- **calibrage** — four series say the threshold is right, one series said wrong (`bb15473`)
- **skills** — write down how to assist a meeting while it runs (`006db91`)
- name the machine's guard by its role, not by its product (`f7d770d`)
- write the engineering log and the calibration notes in English (`367b55f`)
- **readme** — describe the tree that exists, and say what enforces it (`9f7d57a`)
- **assets** — redraw the two diagrams in English, and fix what they hid (`6163c69`)
- **readme** — write the README in English (`082f443`)
- measure the chain against a real four-person meeting (`c53be93`)
- **readme** — stop claiming the chain runs on a Mac's graphics card (`eb6572e`)
- record what real recordings showed, and what the run costs (`0124760`)
- record the first run on a real Linux desktop (`8722c34`)

## Remaniements

- **traiter** — name the report title import for what it is (`73c9d5e`)
- **couches** — put every module in the layer its imports say it belongs to (`0641d59`)

