"""Rédaction du compte rendu par Claude Code, en mode sans interface.

C'est le rédacteur par défaut : la qualité de synthèse d'un compte rendu de
réunion — distinguer une décision d'une hypothèse, rattacher une position à une
personne — reste hors de portée des modèles qu'on fait tourner sur un portable.

Choix assumé et documenté : **la transcription sort du poste** vers l'API
Anthropic. Tout le reste de la chaîne — enregistrement, transcription,
identification des voix — demeure local. Pour ne rien laisser sortir du tout,
`compte_rendu.moteur = "ollama"` branche un modèle local, au prix d'une synthèse
plus grossière.
"""

from __future__ import annotations

import shutil
import subprocess

CONSIGNES = """Tu rédiges le compte rendu d'une réunion de travail, à partir d'une
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

2. `## Décisions` — les décisions effectivement prises, une puce chacune, une à
   deux lignes. Une décision est une chose que le groupe a arrêtée, pas une
   intention ni une hypothèse. S'il n'y en a aucune, écris « Aucune décision
   formelle » et passe à la suite.

3. `## Actions` — un tableau à trois colonnes : Qui, Quoi, Quand. Une ligne par
   action. « Quand » vaut « — » si aucune échéance n'a été dite : ne l'invente
   jamais. Si le responsable n'est pas identifiable, écris « à attribuer ».

4. `## Points ouverts` — ce qui reste non tranché, une puce chacun, avec en une
   demi-ligne ce qui manque pour trancher.

5. `## Détail par sujet` — une sous-section `###` par sujet abordé, titre
   explicite, **trois à cinq phrases** chacune. Dis qui a porté quelle position
   quand c'est identifiable. Une citation entre guillemets seulement si la
   formule exacte compte, jamais plus d'une par sujet.

6. `## Annexe` — **uniquement si la transcription a perdu quelque chose qui change
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


class RedacteurClaude:
    """Rédige le compte rendu en appelant Claude Code en ligne de commande.

    Le modèle est **demandé explicitement** plutôt que laissé au défaut de
    l'outil : celui-ci suit le réglage personnel de qui a installé Claude Code,
    donc le compte rendu changerait de rédacteur sans que personne ne l'ait
    décidé — et pourrait consommer le haut de gamme là où le second suffit
    (voir `CompteRendu.CLAUDE_PAR_DEFAUT`).
    """

    def __init__(self, modele: str = "", commande: str = "claude",
                 delai: int = 900) -> None:
        self.modele = modele
        self.commande = commande
        self.delai = delai

    def rediger(self, transcription: str) -> str:
        if shutil.which(self.commande) is None:
            raise RuntimeError(
                f"« {self.commande} » est introuvable dans le PATH. "
                "Installe Claude Code, ou bascule « compte_rendu.moteur » sur « ollama »."
            )
        # Le texte passe par l'entrée standard : une transcription d'une heure
        # dépasse largement la taille admise pour un argument de commande.
        commande = [self.commande, "-p", "--output-format", "text", "--allowed-tools", ""]
        if self.modele:
            commande += ["--model", self.modele]
        resultat = subprocess.run(
            commande,
            input=CONSIGNES + transcription,
            capture_output=True, text=True, timeout=self.delai, check=False,
        )
        texte = resultat.stdout.strip()
        if resultat.returncode != 0 or not texte:
            details = (resultat.stderr or "").strip().splitlines()
            raise RuntimeError(
                "Claude Code n'a rien produit"
                + (f" : {details[-1]}" if details else ".")
            )
        return texte
