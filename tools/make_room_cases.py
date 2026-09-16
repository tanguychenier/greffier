#!/usr/bin/env python3
"""Turns a clean synthesised meeting into the rooms it is actually held in.

`make_meeting.py` gives two clear voices, close to the microphone, in silence.
No meeting is like that. This file takes that recording and puts it through
what a room does to it, so the chain can be measured on conditions it will
meet rather than on the only one it never will:

    loin        one voice drops 18 dB halfway through, as somebody leaning back
    bruit       a steady background at a chosen signal-to-noise ratio
    tard        a third voice arrives only in the last minute
    ensemble    two people speaking over each other

    python3 tools/make_room_cases.py output/            # all of them
    python3 tools/make_room_cases.py output/ --cas loin

Everything is done on the samples, with no synthesis engine beyond the one that
made the meeting: these cases run wherever the tests run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Mesuré : a voice 18 dB down is what somebody sitting back from the table
#: gives, and it used to cost 0.05 of similarity to their own voice, enough to
#: make them a second person.
RECUL_DB = -18.0

#: A meeting room with air conditioning sits around 20 dB of signal to noise.
RAPPORT_BRUIT_DB = 20.0


def _lire(path: Path) -> tuple[np.ndarray, int]:
    data, hz = sf.read(path, dtype="float32", always_2d=True)
    return data, hz


def loin(source: Path, destination: Path, db: float = RECUL_DB) -> Path:
    """The second half quieter, as if one voice had moved away."""
    data, hz = _lire(source)
    milieu = len(data) // 2
    output_ = data.copy()
    output_[milieu:] *= 10 ** (db / 20)
    sf.write(destination, output_, hz)
    return destination


def bruit(source: Path, destination: Path, rapport_db: float = RAPPORT_BRUIT_DB) -> Path:
    """A steady background, at a stated signal-to-noise ratio."""
    data, hz = _lire(source)
    puissance = float(np.mean(data ** 2)) or 1e-12
    ampleur = float(np.sqrt(puissance / (10 ** (rapport_db / 10))))
    tirage = np.random.default_rng(11)
    output_ = data + tirage.normal(0, ampleur, data.shape).astype("float32")
    sf.write(destination, np.clip(output_, -1.0, 1.0), hz)
    return destination


#: Somebody who says one sentence at the very end of the meeting. Written as a
#: dialogue rather than cut out of the audio: a voice that holds six seconds in
#: an hour is the case the chain used to turn into a person of its own, and it
#: has to be a real second timbre for the test to mean anything.
TARD = [
    ("A", "Nous avons fait le tour du calendrier de la recette, des deux anomalies "
          "remontées lundi, et de la procédure de retour arrière."),
    ("A", "La préproduction est en place depuis vendredi, sans aucun incident sur "
          "les traitements de nuit, ce qui nous laisse la marge nécessaire."),
    ("A", "Je préviendrai les utilisateurs mercredi en fin de journée, et la mise "
          "en production suivra dès le lendemain matin."),
    ("B", "Une seule remarque avant de conclure : pensez au message aux services."),
]


def tard(source: Path, destination: Path) -> Path:
    """A voice that says one sentence, at the very end.

    Built from its own dialogue and not cut out of the audio: what is being
    tested is a real second person holding almost nothing, which is the case
    the chain used to turn into somebody of their own.
    """
    from make_meeting import make

    return make(destination, dialogue=TARD)


def ensemble(source: Path, destination: Path, part: float = 0.3) -> Path:
    """Two people over each other, for a stretch of the meeting."""
    data, hz = _lire(source)
    start = int(len(data) * 0.35)
    longueur = int(len(data) * part)
    output_ = data.copy()
    other = data[:longueur] * 0.8
    end = min(start + longueur, len(output_))
    output_[start:end] += other[: end - start]
    sf.write(destination, np.clip(output_, -1.0, 1.0), hz)
    return destination


CAS = {"loin": loin, "bruit": bruit, "tard": tard, "ensemble": ensemble}


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("sortie", type=Path)
    analyseur.add_argument("--cas", choices=sorted(CAS))
    analyseur.add_argument("--source", type=Path)
    read_ = analyseur.parse_args()

    read_.output_.mkdir(parents=True, exist_ok=True)
    source = read_.source
    if source is None:
        from make_meeting import make

        source = make(read_.output_ / "propre.wav")
    for name, fabrique in sorted(CAS.items()):
        if read_.cas and name != read_.cas:
            continue
        path = fabrique(source, read_.output_ / f"{name}.wav")
        print(f"{name:9} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
