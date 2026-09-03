"""Rédaction du compte rendu par un modèle local servi par Ollama.

Rien ne sort du poste : c'est la seule voie qui tient la promesse du « tout en
local » jusqu'au bout de la chaîne.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

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


class RedacteurOllama:
    def __init__(self, modele: str, hote: str = "http://127.0.0.1:11434") -> None:
        self.modele = modele
        self.hote = hote.rstrip("/")

    def rediger(self, transcription: str) -> str:
        corps = json.dumps({
            "model": self.modele,
            "prompt": CONSIGNES + transcription,
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
