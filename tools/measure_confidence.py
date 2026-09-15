#!/usr/bin/env python3
"""Mesure ce que vaut la confiance rendue par le modèle.

Whisper donne un `avg_logprob` par segment ; son exponentielle est la
probabilité moyenne par jeton. Reste à savoir si ce chiffre sépare vraiment les
tours justes des tours faux, et où poser la limite. Personne ne l'avait mesuré,
et un seuil non mesuré est un seuil inventé.

    .venv/bin/python tools/measure_confidence.py reunion.wav reference.txt

`reference.txt` porte le texte attendu, une ligne par tour de parole, dans
l'ordre. Le script transcrit, aligne chaque tour sur sa référence, et range les
tours par confiance en disant, pour chaque palier, combien de mots sont faux
au-dessus et au-dessous.

Sans argument, il fabrique lui-même une réunion avec `tools/make_meeting.py`,
donc avec la synthèse vocale installée sur la machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))


def _bare(text: str) -> list[str]:
    """Les mots seuls : ni ponctuation, ni majuscules, ni traits d'union.

    Le modèle choisit sa ponctuation et ses coupures ; « Jacques. Je vous »
    contre « Jacques, je vous » est la même phrase entendue pareil, et la
    compter comme deux mots faux noie les vraies erreurs.
    """
    import re
    import unicodedata

    depouille = unicodedata.normalize("NFD", text.lower().replace("-", ""))
    sans_accents = "".join(c for c in depouille if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9']+", sans_accents)


def _word_errors(said: str, expected: str) -> tuple[int, int]:
    """Mots faux et mots attendus, par la distance d'édition sur les mots."""
    from rapidfuzz.distance import Levenshtein

    attendus = _bare(expected)
    return Levenshtein.distance(_bare(said), attendus), len(attendus)


def _transcribe(audio: Path, language: str = "fr") -> list[object]:
    from greffier.adapters.configuration import Config
    from greffier.wiring import _transcriber

    config = Config()
    engine = _transcriber(config)
    print(f"  transcription de {audio.name}…", flush=True)
    return list(engine.transcribe(audio, language, ""))


def _aligned(utterances: list[object], reference: list[str]) -> list[tuple[object, str]]:
    """Chaque tour avec la ligne de référence la plus proche, dans l'ordre.

    Le découpage du modèle ne suit pas celui de la référence : deux phrases
    peuvent tomber dans un segment. On avance donc dans la référence au fur et
    à mesure, ce qui suffit pour un jeu d'essai dont l'ordre est connu.
    """
    out = []
    reste = list(reference)
    for utterance in utterances:
        if not reste:
            break
        out.append((utterance, reste.pop(0)))
    return out


def _say_what_differs(paires: list[tuple[object, str]]) -> None:
    """Les mots qui ne sont pas les bons, pour juger de ce qu'on mesure.

    Un taux d'erreur sans les mots derrière ne se relit pas : la première
    version de ce script comptait « pré-production » contre « préproduction »
    comme deux mots faux, et l'écart mesuré était le sien, pas celui du modèle.
    """
    from rapidfuzz.distance import Levenshtein

    for utterance, attendu in paires:
        dits, attendus = _bare(getattr(utterance, "text", "")), _bare(attendu)
        ecarts = [
            (geste, dits[i] if i < len(dits) else "",
             attendus[j] if j < len(attendus) else "")
            for geste, i, _, j, _ in Levenshtein.opcodes(dits, attendus)
            if geste != "equal"
        ]
        if ecarts:
            print("    écarts : " + ", ".join(
                f"« {dit or '∅'} » au lieu de « {attendu_mot or '∅'} »"
                for _, dit, attendu_mot in ecarts
            ))


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    audio = Path(sys.argv[1])
    reference = [
        line.strip() for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not audio.exists():
        print(f"✗ {audio} est introuvable")
        return 1

    paires = _aligned(_transcribe(audio), reference)
    if not paires:
        print("✗ rien n'a été transcrit")
        return 1

    mesures = []
    for utterance, attendu in paires:
        faux, total = _word_errors(getattr(utterance, "text", ""), attendu)
        mesures.append((getattr(utterance, "confidence", None), faux, total,
                        getattr(utterance, "text", "")))

    juges = [m for m in mesures if m[0] is not None]
    if not juges:
        print("✗ le moteur n'a rendu aucune confiance : rien à mesurer")
        return 1

    print(f"\n{len(juges)} tour(s) jugé(s) sur {len(mesures)}\n")
    _say_what_differs(paires)
    print("  confiance   mots faux / attendus   texte")
    for confiance, faux, total, texte in sorted(juges, key=lambda m: m[0] or 0.0):
        marque = "✗" if faux else " "
        print(f"  {confiance:>9.2f}   {marque} {faux:>3} / {total:<3}"
              f"           {texte[:56]}")

    justes = [m[0] for m in juges if m[1] == 0]
    fautifs = [m[0] for m in juges if m[1] > 0]
    print()
    if justes:
        print(f"  tours justes    : {len(justes)}, confiance de "
              f"{min(justes):.2f} à {max(justes):.2f}")
    if fautifs:
        print(f"  tours fautifs   : {len(fautifs)}, confiance de "
              f"{min(fautifs):.2f} à {max(fautifs):.2f}")
    if justes and fautifs and max(fautifs) < min(justes):
        limite = (max(fautifs) + min(justes)) / 2
        print(f"\n  Les deux ne se recouvrent pas : la limite tombe à {limite:.2f}")
    elif justes and fautifs:
        print("\n  Les deux se recouvrent : aucun seuil ne les sépare "
              "proprement sur ce jeu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
