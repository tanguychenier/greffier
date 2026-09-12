"""Writing the minutes with Claude Code, through its command line.

The only link in the chain that leaves the machine, and a deliberate one:
telling a decision from a hypothesis and tying a position to a person is out of
reach of models that run on a laptop.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from greffier.domain.languages import name_of

GUIDANCE = """Tu rédiges le compte rendu d'une réunion de travail, à partir d'une
transcription automatique locale dont les locuteurs ont été identifiés.

Ce document est lu par les participants et par des absents. Ils y cherchent trois
choses : ce qui a été décidé, ce qu'ils ont à faire, ce qui reste en suspens. Tout
le reste est secondaire.

Structure attendue, en français, au format Markdown, dans cet ordre :

1. Un titre : « Compte rendu : <sujet de la réunion> ». Deux-points, pas de
   tiret : voir la règle de typographie plus bas, elle vaut aussi pour le titre.
   Puis, si le contexte t'en donne une, **la ligne de contexte reproduite mot
   pour mot** : date, horaires, durée, participants. Ne la reformule pas, ne
   réordonne rien, n'y ajoute rien. Elle est composée pour toi parce qu'une date
   et une heure ne sont pas matière à style. Si aucune ligne ne t'est donnée,
   n'en invente pas.

2. `## Décisions`, les décisions effectivement prises, une puce chacune, une à
   deux lignes. Une décision est une chose que le groupe a arrêtée, pas une
   intention ni une hypothèse. S'il n'y en a aucune, écris « Aucune décision
   formelle » et passe à la suite.

3. `## Actions`, un tableau à trois colonnes : Qui, Quoi, Quand. Une ligne par
   action. « Quand » vaut « - » si aucune échéance n'a été dite : ne l'invente
   jamais. Si le responsable n'est pas identifiable, écris « à attribuer ».

4. `## Points ouverts`, ce qui reste non tranché, une puce chacun, avec en une
   demi-ligne ce qui manque pour trancher.

5. `## Détail par sujet`, une sous-section `###` par sujet abordé, titre
   explicite, **trois à cinq phrases** chacune. Dis qui a porté quelle position
   quand c'est identifiable. Une citation entre guillemets seulement si la
   formule exacte compte, jamais plus d'une par sujet.

6. `## Annexe`, **uniquement si la transcription a perdu quelque chose qui change
   la lecture** : termes manifestement mal transcrits, passages inaudibles portant
   sur une décision ou une échéance. Trois lignes au maximum. Si la transcription
   est fiable, omets cette section entièrement.

Densité. Chaque phrase apporte un fait que le lecteur n'a pas encore : un
chiffre, un nom, une cause, une conséquence, une date. Tu supprimes tout le
reste, en particulier :

- les phrases de liaison et d'annonce (« plusieurs points ont été abordés »,
  « il convient de noter que », « un échange a eu lieu sur ») ;
- les redites d'une section à l'autre : une décision déjà listée ne se raconte
  pas une seconde fois dans le détail, on n'y met que ce qui l'explique ;
- les qualificatifs qui n'ajoutent rien (« important », « intéressant »,
  « crucial »). Si un point est important, sa place dans le document le dit.

Un compte rendu dense n'est pas un compte rendu tronqué : aucune décision,
aucune action, aucun point ouvert ne disparaît. C'est le verbiage autour qui
disparaît.

Typographie. **Aucun tiret cadratin ni demi-cadratin dans le texte** : ni « — »
ni « – », ni comme incise, ni comme substitut de deux-points, ni pour marquer une
valeur absente. Ils donnent au document l'allure d'un texte produit par une
machine. Emploie la virgule, les deux-points, la parenthèse ou le point selon le
sens. Dans la colonne « Quand », une échéance non dite s'écrit « non dit ». Les
tirets restent permis là où la syntaxe Markdown les exige : séparateurs de
tableau et puces de liste.

Ce que tu ne fais jamais :

- Ne parle pas de la mécanique de l'outil. Les étiquettes « Personne N », les
  ruptures de segmentation, la fiabilité des rapprochements de voix : c'est de la
  plomberie, elle n'a rien à faire dans un compte rendu. Nomme simplement les
  participants ; ignore les fragments non attribués.
- N'horodate pas les propos. Un compte rendu n'est pas un relevé minuté.
- N'invente aucun fait, aucune décision, aucune échéance qui ne soit dans la
  transcription. Si un point est incompréhensible, dis-le en une demi-ligne
  plutôt que de le combler.
- N'attribue aucun pronom genré à une personne dont le genre n'est pas explicite
  dans la transcription : emploie des formulations neutres.
- Ne commente pas ta démarche, pas de préambule, pas de conclusion sur ton
  travail : produis directement le document.

Mots déformés. La transcription est faite par une machine, sur de la parole
spontanée : elle rend parfois un mot par un autre qui sonne pareil sans exister
(« diemandie » pour « demander »), colle deux mots, ou francise un terme
technique. Trois règles, dans cet ordre :

- **Rétablis le mot** quand la phrase et le sujet ne laissent aucun doute, et
  écris-le normalement, sans signaler la correction. Un compte rendu n'est pas
  une édition critique.
- **Ne cite jamais entre guillemets une forme que tu as dû deviner.** Une
  citation exacte n'a de valeur que si elle est exacte : reformule au style
  indirect plutôt que de figer une déformation.
- **Ne devine pas ce qui porte l'information** : un nom propre, un chiffre, une
  échéance, un identifiant. Si le mot déformé est justement celui qui décide,
  dis en une demi-ligne ce qui manque, dans l'annexe, et n'inscris pas de valeur
  inventée dans le tableau des actions.

Un terme technique déformé se rétablit d'après le vocabulaire du contexte quand
il est fourni en amorce ; en son absence, préfère la formulation générale à un
sigle deviné.

Longueur : viser deux à trois pages pour une réunion d'une heure. Un compte rendu
qu'on ne lit pas ne sert à rien.

Transcription :
"""

_MENTION_DE_LANGUE = "Structure attendue, en français,"
_MENTION_NUE = "Structure attendue, en"

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

CONSIGNES_CONVERSATION = """Tu assistes quelqu'un pendant ou après une réunion de
travail. On te donne ce qui s'est dit, puis une question.

Réponds brièvement, en français, sans plan ni titres : c'est une conversation,
pas un document.

Ce sur quoi tu t'appuies, dans cet ordre :

1. Ce qui a été dit. C'est la source qui fait autorité sur cette réunion.
2. Ce que tu peux chercher en ligne, quand la question porte sur un fait
   extérieur à la réunion : une définition, une norme, une version, l'état d'un
   service, une documentation. Cherche de ton propre chef quand cela répond
   mieux, sans attendre qu'on te le demande.

Quand tu as cherché, **donne l'adresse**. Une réponse sans sa source ne se
vérifie pas, et c'est en réunion qu'on a besoin de pouvoir ouvrir le lien tout
de suite. Une ligne par source, l'URL complète, pas « selon la documentation ».

Termine par ce que tu proposes, quand tu as quelque chose à proposer : une
piste à vérifier, une question à poser à quelqu'un, un point qui manque pour
trancher. Une seule ligne, précédée de « À faire : ». N'invente rien pour
remplir cette ligne : s'il n'y a rien à proposer, n'en mets pas.

Ce que tu ne fais jamais :

- présenter comme décidé ce qui est en train d'être discuté. Une transcription
  en direct est partielle et comporte des erreurs de mots.
- combler un trou de la transcription par ce que tu as trouvé ailleurs. Si la
  réponse n'est pas dans ce qui a été dit et que tu ne l'as pas cherchée,
  dis-le.
- envoyer vers un moteur de recherche des noms de personnes, des extraits de
  propos, ou quoi que ce soit d'interne. Tu cherches le terme général, jamais
  la phrase de la réunion.

N'emploie ni tiret cadratin ni demi-cadratin.
"""

def _event(line: str) -> dict[str, object] | None:
    """One line of the stream, or None when it is not one.

    A stream is not a contract: a version that prefixes a warning, or breaks a
    line, must cost the answer nothing.
    """
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        read = json.loads(line)
    except json.JSONDecodeError:
        return None
    return read if isinstance(read, dict) else None


def _is_a_search(event: dict[str, object], tools: tuple[str, ...]) -> bool:
    """Whether this event is the assistant reaching for the web."""
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") in tools
        for block in content
    )


class ClaudeWriter:
    """Writes the minutes by calling Claude Code."""

    SEARCH_TOOLS: ClassVar[tuple[str, ...]] = ("WebSearch", "WebFetch")

    def __init__(self, model: str = "", command: str = "claude",
                 timeout: int = 900, language: str = "",
                 tools: tuple[str, ...] = (), consignes_propres: str = "",
                 on_search: Callable[[], None] | None = None) -> None:
        self.model = model
        self.command = command
        self.timeout = timeout
        self.language = language
        self.tools = tools
        self.consignes_propres = consignes_propres
        #: Called the moment a search actually starts, never when one merely
        #: might. Without it the call keeps its plain text output, which is
        #: cheaper to read and is all the minutes need.
        self.on_search = on_search

    def write_up(self, transcription: str) -> str:
        if shutil.which(self.command) is None:
            raise RuntimeError(
                f"« {self.command} » est introuvable dans le PATH. "
                "Installe Claude Code, ou bascule « compte_rendu.moteur » sur « ollama »."
            )
        # `--strict-mcp-config` keeps the machine's own MCP servers out of the
        # call: this assistant has no business loading them, and measured over
        # seven runs it also takes 0.3 s off a round trip that costs 3.
        format_de_sortie = ["stream-json", "--verbose"] if self.on_search else ["text"]
        command = [self.command, "-p", "--output-format", *format_de_sortie,
                    "--strict-mcp-config",
                    "--allowed-tools", ",".join(self.tools)]
        if self.model:
            command += ["--model", self.model]
        header = self.consignes_propres or guidance(self.language)
        if self.on_search is not None:
            return self._answer_watching_the_stream(command, header + transcription)
        outcome = subprocess.run(
            command,
            input=header + transcription,
            capture_output=True, text=True, timeout=self.timeout, check=False,
        )
        text = outcome.stdout.strip()
        if outcome.returncode != 0 or not text:
            details = (outcome.stderr or "").strip().splitlines()
            raise RuntimeError(
                "Claude Code n'a rien produit"
                + (f" : {details[-1]}" if details else ".")
            )
        return text

    def _answer_watching_the_stream(self, command: list[str], prompt: str) -> str:
        """Reads the events as they arrive, to know when a search starts.

        The plain text output says what was answered and nothing about how. The
        stream carries one event per step, so a search is known the moment it
        starts rather than guessed from the fact that tools were allowed -- and
        a cue that sounds on every question would say nothing at all.

        The prompt goes in through a file rather than a pipe we keep writing
        to: a long transcription fills the pipe's buffer, and the two processes
        would then wait for each other, one to write and one to be read.
        """
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", encoding="utf-8", delete=False
        ) as fichier:
            fichier.write(prompt)
            question = Path(fichier.name)
        cherche_deja = False
        text = ""
        try:
            with question.open(encoding="utf-8") as entree:
                process = subprocess.Popen(
                    command, stdin=entree, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True,
                )
                for ligne in process.stdout or ():
                    evenement = _event(ligne)
                    if evenement is None:
                        continue
                    if not cherche_deja and _is_a_search(evenement, self.SEARCH_TOOLS):
                        cherche_deja = True
                        if self.on_search is not None:
                            self.on_search()
                    if evenement.get("type") == "result":
                        text = str(evenement.get("result") or "").strip()
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    raise
                erreurs = (process.stderr.read() if process.stderr else "").strip()
        finally:
            question.unlink(missing_ok=True)
        if process.returncode != 0 or not text:
            details = erreurs.splitlines()
            raise RuntimeError(
                "Claude Code n'a rien produit"
                + (f" : {details[-1]}" if details else ".")
            )
        return text
