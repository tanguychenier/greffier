"""Writing the minutes with a local model, for whoever wants nothing to leave."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request

from greffier.domain.languages import name_of

GUIDANCE = """Tu rédiges le compte rendu d'une réunion de travail, à partir d'une
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

def guidance(language: str = "") -> str:
    """The instructions, dictated in the language wanted."""
    if not language or language == "fr":
        return GUIDANCE
    name = name_of(language)
    header = (
        f"Rédige entièrement en {name}. Tout le document : le titre, les intitulés\n"
        f"de section, les phrases. La transcription qui suit peut être dans une\n"
        f"autre langue : cela ne change rien à la langue du compte rendu.\n\n"
    )
    return header + GUIDANCE.replace(_MENTION_DE_LANGUE, f"{_MENTION_NUE} {name}") + (
        f"\n\nRappel : le compte rendu s'écrit en {name}.\n"
    )

def available_models() -> list[str]:
    """The models Ollama already has on this machine."""
    try:
        output = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=False, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.split()[0] for line in output.splitlines()[1:] if line.strip()]

class OllamaWriter:
    def __init__(self, model: str, hote: str = "http://127.0.0.1:11434",
                 language: str = "") -> None:
        self.model = model
        self.hote = hote.rstrip("/")
        self.language = language

    def write_up(self, transcription: str) -> str:
        corps = json.dumps({
            "model": self.model,
            "prompt": guidance(self.language) + transcription,
            "stream": False,
            "options": {"temperature": 0.2},
        }).encode("utf-8")
        requete = urllib.request.Request(
            f"{self.hote}/api/generate", data=corps,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(requete, timeout=900) as response:
                text = str(json.load(response).get("response", "")).strip()
        except urllib.error.URLError as erreur:
            raise RuntimeError(
                f"Ollama injoignable sur {self.hote} : {erreur}. "
                "Lance « ollama serve », ou change « compte_rendu.moteur »."
            ) from erreur
        if not text:
            raise RuntimeError(f"Le modèle {self.model} n'a rien produit.")
        return text
