#!/usr/bin/env python3
"""Fabrique une fausse réunion à deux voix, pour les tests d'intégration.

Les vraies réunions ne peuvent pas servir de jeu d'essai : elles contiennent des
échanges de travail et des voix identifiables. On synthétise donc un dialogue
avec deux voix du système, ce qui donne un fichier audio réel — passé par le
même chemin que n'importe quel enregistrement — sans la moindre donnée
personnelle, et rejouable par qui veut.

    python3 outils/fabriquer_reunion.py sortie.wav

macOS uniquement pour l'instant : « say » est le seul moteur de synthèse
disponible sans rien installer. Sur Linux, « espeak-ng » ferait l'affaire.
"""

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Le dialogue est écrit pour exercer les trois façons de nommer quelqu'un, et
# pour que chaque voix accumule assez d'indices pour être certaine :
#   Jacques  auto-présentation (3) + « Merci Jacques » (1) = 4
#   Sandy    interpellation (2) + « Merci Sandy » (1)      = 3
# Chaque réplique dépasse trois secondes, seuil en deçà duquel une empreinte
# vocale ne porte pas assez de voix pour être exploitable.
DIALOGUE = [
    ("A", "Bonjour à tous, moi c'est Jacques, je vous propose de commencer par le "
          "point sur la recette, qui nous occupe depuis le début de la semaine."),
    ("B", "Merci Jacques. De mon côté, le déploiement en préproduction est terminé "
          "depuis vendredi dernier, et tout s'est déroulé sans incident notable."),
    ("A", "Sandy, tu peux nous dire où en sont les anomalies bloquantes sur le "
          "module de facturation, celles que nous avions relevées la semaine dernière ?"),
    ("B", "Il en reste exactement deux. Elles sont corrigées depuis hier soir, mais "
          "elles ne sont pas encore validées par l'équipe fonctionnelle."),
    ("A", "Merci Sandy. On décale donc la recette à jeudi prochain, et nous "
          "préviendrons l'ensemble des utilisateurs concernés mercredi en fin de journée."),
]

# Une seconde réunion, avec les mêmes voix mais **aucun prénom prononcé**. Elle
# sert à prouver la banque de voix : si des noms apparaissent malgré tout, ils ne
# peuvent venir que de la reconnaissance vocale.
DIALOGUE_SANS_NOMS = [
    ("A", "On reprend là où nous nous étions arrêtés la dernière fois, avec le "
          "calendrier de la semaine prochaine et les points encore en suspens."),
    ("B", "Les deux anomalies sont validées depuis ce matin, la version peut donc "
          "partir en production dès que vous donnez votre accord."),
    ("A", "Parfait, dans ce cas nous lançons la mise en production demain matin, "
          "et je préviens les utilisateurs dès cet après-midi par courriel."),
    ("B", "Je prépare la procédure de retour arrière au cas où, et je la partagerai "
          "avec l'équipe avant la fin de la journée."),
]

# Une réunion tenue **autour d'une table** : trois personnes, un seul micro,
# aucune boucle système. Le canal ne désigne alors personne, et c'est tout
# l'intérêt du cas — c'est la seule configuration où l'attribution ne repose que
# sur la segmentation et la banque de voix.
DIALOGUE_PRESENTIEL = [
    ("A", "Bonjour à tous, moi c'est Jacques, on se retrouve autour de la table pour "
          "faire le point sur le calendrier de la recette, qui nous occupe depuis lundi."),
    ("B", "Merci Jacques. De mon côté la préproduction est en place depuis vendredi, "
          "et je n'ai relevé aucun incident sur les traitements de nuit."),
    ("A", "Pierre, tu peux nous dire où en est la reprise des données, celle que nous "
          "avions repoussée la semaine dernière ?"),
    ("C", "Elle est terminée depuis hier soir. Il reste à valider les écarts de "
          "facturation, ce que l'équipe fonctionnelle fera demain matin."),
    ("A", "Merci Pierre. On garde donc jeudi pour la recette, et nous préviendrons "
          "les utilisateurs mercredi en fin de journée."),
    ("B", "Je m'occupe du message aux utilisateurs, et je le fais relire avant de "
          "l'envoyer à l'ensemble des services concernés."),
]

#: Trois voix pour le présentiel. Sandy ne se présente pas et n'est jamais
#: interpellée : elle doit rester une voix à nommer, sinon c'est que la chaîne
#: invente.
VOIX_PRESENTIEL = {"A": "Jacques", "B": "Sandy", "C": "Rocko"}

#: Fuite mesurée dans la boucle système d'une réunion tenue autour d'une table :
#: -53 dB au lieu du silence attendu, du son y ayant fui à un moment. C'est
#: **exactement** le cas qui piégeait le verdict, quand une boucle non nulle
#: suffisait à conclure « visio » — d'où une fuite dans le fichier d'essai, et
#: non un second canal muet qui rendrait l'épreuve trop facile.
FUITE_DB = -40.0


# Deux voix aussi éloignées que possible : la segmentation doit pouvoir les
# distinguer, sinon le test mesurerait la synthèse vocale et non la chaîne.
VOIX = {"A": "Jacques", "B": "Sandy"}
SILENCE = 0.4  # secondes entre deux répliques, comme dans une vraie discussion


def fabriquer(destination: Path, voix: dict | None = None, dialogue=None) -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("la synthèse « say » n'existe que sur macOS")
    if not shutil.which("say") or not shutil.which("ffmpeg"):
        raise RuntimeError("« say » et « ffmpeg » sont nécessaires")

    voix = voix or VOIX
    dialogue = dialogue if dialogue is not None else DIALOGUE
    with tempfile.TemporaryDirectory() as dossier:
        travail = Path(dossier)
        morceaux = []
        for index, (locuteur, texte) in enumerate(dialogue):
            brut = travail / f"{index:02d}.aiff"
            subprocess.run(
                ["say", "-v", voix[locuteur], "-o", str(brut), texte],
                check=True, capture_output=True,
            )
            morceaux.append(brut)

        silence = travail / "silence.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"anullsrc=r=16000:cl=mono:d={SILENCE}", str(silence)],
            check=True,
        )

        liste = travail / "liste.txt"
        entrees = []
        for morceau in morceaux:
            converti = morceau.with_suffix(".wav")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(morceau),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(converti)],
                check=True,
            )
            entrees += [converti, silence]
        liste.write_text(
            "\n".join(f"file '{chemin}'" for chemin in entrees) + "\n", encoding="utf-8"
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(liste), "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(destination)],
            check=True,
        )
    return destination


def fabriquer_presentiel(destination: Path) -> Path:
    """Fabrique une réunion de table : trois voix sur le micro, une boucle qui fuit.

    Le fichier est **stéréo**, comme ce que rend le périphérique d'enregistrement :
    canal 0 le micro, canal 1 la boucle système. Autour d'une table, la boucle ne
    porte rien d'utile — juste la fuite mesurée à -53 dB sur la vraie réunion.

    Un second canal strictement muet aurait rendu l'épreuve trop facile : c'est
    précisément la fuite qui faisait conclure « visio » à tort, et attribuait
    toute la réunion à la personne qui enregistrait.
    """
    with tempfile.TemporaryDirectory() as dossier:
        melange = Path(dossier) / "micro.wav"
        fabriquer(melange, voix=VOIX_PRESENTIEL, dialogue=DIALOGUE_PRESENTIEL)
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(melange),
             "-filter_complex",
             f"[0:a]asplit=2[m][f];[f]volume={FUITE_DB}dB[b];[m][b]amerge=inputs=2[s]",
             "-map", "[s]", "-ar", "16000", "-ac", "2", "-c:a", "pcm_s16le",
             str(destination)],
            check=True,
        )
    return destination


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("sortie", type=Path)
    analyseur.add_argument(
        "--presentiel", action="store_true",
        help="trois voix autour d'une table, en stéréo, au lieu de deux en mono",
    )
    arguments = analyseur.parse_args()
    chemin = (
        fabriquer_presentiel(arguments.sortie)
        if arguments.presentiel
        else fabriquer(arguments.sortie)
    )
    duree = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(chemin)], capture_output=True, text=True, check=False,
    ).stdout.strip()
    repliques, voix, canaux = (
        (len(DIALOGUE_PRESENTIEL), 3, "stéréo")
        if arguments.presentiel
        else (len(DIALOGUE), 2, "mono")
    )
    print(f"{chemin} — {float(duree):.1f} s, {repliques} répliques, {voix} voix, {canaux}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
