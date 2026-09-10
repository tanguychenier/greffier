#!/usr/bin/env python3
"""Quels prénoms le modèle de transcription rend-il de façon reconnaissable ?

L'assistant répond quand on cite son prénom. Un prénom que la transcription ne
rend pas est donc un assistant sourd — et rien ne le dirait à celui qui l'a
choisi : il appellerait dans le vide, et conclurait que l'outil ne marche pas.

Chaque candidat passe quatre épreuves — deux tournures, deux voix de synthèse —
puis cinq pièges : des phrases sans le prénom, pour vérifier qu'il ne s'y
déclenche pas. C'est le défaut de « Greffier », que « le greffe du tribunal »
suffisait à réveiller, et d'« Élise », que « elle a lu ci et ça » appelle.

Retenu : quatre appels sur quatre, zéro faux positif sur cinq. Un prénom reconnu
une fois sur deux ne vaut rien, puisqu'on appelle une fois et qu'on attend.

    python3 outils/eprouver_les_prenoms.py

**Aucun son n'est joué** : les fichiers sont écrits puis transcrits. On peut
donc le lancer pendant une réunion — même si le calcul, lui, se dispute le
processeur avec la transcription en direct.

Ce qu'il ne mesure pas : ce qu'un prénom devient prononcé par une vraie voix, à
trois mètres d'un micro de table. C'est un plancher, pas une garantie.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
from greffier.adaptateurs.configuration import Config
from greffier.composition import transcripteur_leger
from greffier.domaine.participation import appelee

FEMININS = ["Lucie", "Camille", "Alice", "Manon", "Louise", "Élise", "Iris"]
MASCULINS = ["Martin", "Julien", "Antoine", "Nicolas", "Marius", "Léon", "Basile"]

#: Deux tournures, deux voix : un prénom qui ne passe qu'une fois sur deux ne
#: vaut rien, puisqu'on l'appelle une fois et on attend.
PHRASES = ["{}, est-ce que tu peux noter ça ?",
           "Du coup {}, tu en penses quoi ?"]
VOIX = ["Thomas", "Amélie"]

#: Ce sur quoi le prénom ne doit **pas** se déclencher. Le piège de
#: « Greffier », que « le greffe du tribunal » suffisait à réveiller.
PIEGES = [
    "on passe au point suivant, la recette est terminée",
    "il faut qu'on parle du budget et des livraisons",
    "le sprint avance bien, la merge request est prête",
    "elle a lu ci et ça dans la documentation",
    "on a vu ça lundi avec l'équipe de Bordeaux",
]

transcripteur = transcripteur_leger(Config())
if transcripteur is None:
    raise SystemExit("aucun modèle de transcription")


def entendu(voix, phrase, dossier):
    brut, wav = dossier / "p.aiff", dossier / "p.wav"
    subprocess.run(["say", "-v", voix, "-o", str(brut), phrase],
                   check=False, capture_output=True)
    if not brut.exists():
        return ""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                    str(brut), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(wav)], check=False, capture_output=True)
    brut.unlink(missing_ok=True)
    if not wav.exists():
        return ""
    rendu = " ".join(r.texte for r in transcripteur.transcrire(wav, "fr", ""))
    wav.unlink(missing_ok=True)
    return rendu


print(f"{'prénom':10} {'appels reconnus':>16} {'faux positifs':>15}   exemple entendu")
print("─" * 84)
with tempfile.TemporaryDirectory() as brut:
    dossier = Path(brut)
    for prenom in FEMININS + MASCULINS:
        reconnus, total, exemple = 0, 0, ""
        for voix in VOIX:
            for phrase in PHRASES:
                texte = entendu(voix, phrase.format(prenom), dossier)
                total += 1
                if appelee(texte, prenom):
                    reconnus += 1
                elif not exemple:
                    exemple = texte[:44]
        faux = sum(1 for p in PIEGES if appelee(p, prenom))
        marque = "  ✓" if reconnus == total and faux == 0 else "  ✗"
        print(f"{prenom:10} {reconnus:>10}/{total}      {faux:>10}/{len(PIEGES)}"
              f"{marque} {exemple}")
