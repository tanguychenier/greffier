# Journal des modifications

Engendré depuis les messages de commit (convention Angular) :

    python3 outils/journal_des_modifications.py > CHANGELOG.md

## Nouveautés

- **domaine** — make the language a domain value instead of an assumption (`b787a49`)
- **transcription** — make the graphics card usable on Linux (`464b13a`)
- Greffier, a local-first meeting assistant (`4e3684f`)

## Corrections

- **fichiers** — stop collapsing non-Latin names to the same identifier (`549efea`)
- **traiter** — keep the meeting when no report is written (`ce19136`)
- **diagnostic** — judge sound capture on the server, not on pactl (`85a3cbd`)
- **interface** — size fonts in pixels and name families Tk guarantees (`7bb4f77`)
- **transcription** — fall back to the processor when the card cannot compute (`2b10cb1`)

## Performance

- **locuteurs** — give the models half the cores instead of one (`cca1e61`)

## Documentation

- **assets** — redraw the two diagrams in English, and fix what they hid (`0406aa6`)
- **readme** — write the README in English (`22efa6f`)
- measure the chain against a real four-person meeting (`aa18e44`)
- **readme** — stop claiming the chain runs on a Mac's graphics card (`2fd7373`)
- record what real recordings showed, and what the run costs (`c38a530`)
- record the first run on a real Linux desktop (`f1e21f9`)

