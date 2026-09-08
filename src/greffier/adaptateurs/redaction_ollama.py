"""Rédaction du compte rendu par un modèle local servi par Ollama.

Rien ne sort du poste : c'est la seule voie qui tient la promesse du « tout en
local » jusqu'au bout de la chaîne.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request

from greffier.domaine.langues import nom_de

CONSIGNES = """Tu rédiges le compte rendu d'une réunion de travail, à partir d'une
transcription automatique locale dont les locuteurs ont été identifiés. Les
personnes non reconnues portent une étiquette « Personne N ».

Attendu, en français, au format Markdown :

1. Un titre et une ligne de contexte (durée, nombre de personnes).
2. Un tableau des intervenants : rôle déduit du contenu et indices qui le
   laissent penser. N'invente jamais un prénom. N'attribue aucun pronom genré à
   une personne dont le genre n'est pas explicite : emploie des formulations neutres.
3. Un résumé PAR THÈME. Dis qui a porté quelle position quand c'est identifiable,
   cite entre guillemets les formules marquantes, et distingue ce qui est décidé
   de ce qui reste ouvert.
4. Une section « Décisions et suites » sous forme de tableau : quoi, qui, quand.
5. Une section « Fiabilité de la transcription » : corrections évidentes que tu as
   appliquées, termes restés douteux, passages où le modèle a manifestement bouclé.

Règles : n'invente aucun fait, aucune décision, aucune échéance qui ne soit dans
la transcription. Si un point est incompréhensible, dis-le plutôt que de le
combler. Pas de préambule : produis directement le document.

Transcription :
"""

_MENTION_DE_LANGUE = "Attendu, en français,"
_MENTION_NUE = "Attendu, en"


def consignes(langue: str = "") -> str:
    """Les consignes, dictées dans la langue voulue.

    Le français rend la constante **caractère pour caractère** : cent lignes
    d'ajustements gagnés sur de vraies réunions, qu'on ne retraduit pas et qu'on
    ne réécrit pas. Pour une autre langue, la même constante, avec la seule
    mention de langue remplacée et une directive posée en tête puis rappelée
    juste avant la transcription — un modèle qui lit cent lignes de français
    retombe volontiers dans le français à la fin d'un long document.

    Ce que les tests prouvent : que l'instruction PART. Qu'un modèle y obéisse
    sur toute la longueur d'un compte rendu, aucun test ne le dira.
    """
    if not langue or langue == "fr":
        return CONSIGNES
    nom = nom_de(langue)
    entete = (
        f"Rédige entièrement en {nom}. Tout le document : le titre, les intitulés\n"
        f"de section, les phrases. La transcription qui suit peut être dans une\n"
        f"autre langue — cela ne change rien à la langue du compte rendu.\n\n"
    )
    return entete + CONSIGNES.replace(_MENTION_DE_LANGUE, f"{_MENTION_NUE} {nom}") + (
        f"\n\nRappel : le compte rendu s'écrit en {nom}.\n"
    )



def modeles_disponibles() -> list[str]:
    """Les modèles qu'Ollama a déjà sur ce poste.

    Ici plutôt que dans l'assistant de première configuration : c'est
    l'adaptateur d'Ollama qui sait parler à Ollama, et la fenêtre allait
    chercher cette liste dans un assistant en terminal, par une fonction
    privée. Rendre la liste vide plutôt que d'échouer : ne pas savoir ce qui
    est installé n'empêche pas de choisir.
    """
    try:
        sortie = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=False, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ligne.split()[0] for ligne in sortie.splitlines()[1:] if ligne.strip()]


class RedacteurOllama:
    def __init__(self, modele: str, hote: str = "http://127.0.0.1:11434",
                 langue: str = "") -> None:
        self.modele = modele
        self.hote = hote.rstrip("/")
        self.langue = langue

    def rediger(self, transcription: str) -> str:
        corps = json.dumps({
            "model": self.modele,
            "prompt": consignes(self.langue) + transcription,
            "stream": False,
            # Température basse : un compte rendu doit coller à ce qui a été dit,
            # pas explorer des tournures.
            "options": {"temperature": 0.2},
        }).encode("utf-8")
        requete = urllib.request.Request(
            f"{self.hote}/api/generate", data=corps,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            # Une heure de réunion peut demander plusieurs minutes de rédaction.
            with urllib.request.urlopen(requete, timeout=900) as reponse:
                texte = str(json.load(reponse).get("response", "")).strip()
        except urllib.error.URLError as erreur:
            raise RuntimeError(
                f"Ollama injoignable sur {self.hote} : {erreur}. "
                "Lance « ollama serve », ou change « compte_rendu.moteur »."
            ) from erreur
        if not texte:
            raise RuntimeError(f"Le modèle {self.modele} n'a rien produit.")
        return texte
