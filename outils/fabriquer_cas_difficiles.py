#!/usr/bin/env python3
"""Fabrique les réunions sur lesquelles la chaîne s'est déjà trompée.

`fabriquer_reunion.py` produit une réunion propre : deux voix nettes, des
prénoms prononcés dans les trois formes attendues. Elle prouve que la chaîne
fonctionne quand tout va bien.

Ce fichier-ci produit l'inverse. Chaque cas reproduit une erreur constatée sur
une réunion réelle, ou un piège que la conception rend possible :

    absent            un prénom cité désigne quelqu'un qui n'est pas là
    sans-reponse      on interpelle quelqu'un qui ne répond pas
    interjections     des mots courants ouvrent les phrases en majuscule
    voix-breve        une personne ne dit que quelques mots de toute la réunion
    trois-voix        trois locuteurs, dont deux proches
    homonymes         un prénom désigne tantôt un présent, tantôt un absent
    proposition-breve une voix courte est nommée par un renvoi, la proposition
                      ne doit pas se perdre avec le fragment qui la porte

    python3 outils/fabriquer_cas_difficiles.py sortie/            # tous
    python3 outils/fabriquer_cas_difficiles.py sortie/ --cas absent

macOS uniquement : « say » est le seul moteur de synthèse disponible sans rien
installer.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabriquer_reunion import fabriquer  # noqa: E402

# Voix nettement distinctes, pour que le test mesure la chaîne et non la
# capacité de la synthèse vocale à faire deux timbres différents.
TROIS_VOIX = {"A": "Jacques", "B": "Amélie", "C": "Grandpa (Français (France))"}
DEUX_VOIX = {"A": "Jacques", "B": "Amélie"}

# Chaque réplique dépasse trois secondes : en deçà, une empreinte vocale ne
# porte pas assez de voix pour être exploitable.
CAS: dict[str, tuple[dict, list[tuple[str, str]]]] = {
    # Laura est citée six fois et ne parle jamais. Elle ne doit apparaître
    # nulle part comme participante. Le compte rendu d'une réunion réelle
    # avait correctement traité ce cas ; il sert de non-régression.
    "absent": (
        DEUX_VOIX,
        [
            ("A", "Laura nous a envoyé son retour hier soir par courriel, et elle "
                  "soulève un point que nous avions complètement laissé de côté."),
            ("B", "Oui, j'ai lu le message de Laura ce matin. Elle a raison sur le "
                  "fond, il faut reprendre cette partie avant la mise en production."),
            ("A", "Laura revient de congé le premier septembre, donc nous attendrons "
                  "son retour avant de trancher définitivement sur ce sujet."),
            ("B", "D'accord. Je note que rien ne bouge avant que Laura ait pu relire "
                  "l'ensemble du dossier et donner son accord formel."),
        ],
    ),
    # Le bug du 25 août : on interpelle quelqu'un, cette personne ne répond
    # pas, et son prénom se colle à la voix qui parle ensuite.
    "sans-reponse": (
        DEUX_VOIX,
        [
            ("A", "Tanguy, tu peux nous sortir les horaires exacts du traitement "
                  "automatique, ceux que tu avais réglés la semaine dernière ?"),
            ("A", "Bon, je poursuis en attendant. Le déploiement est prévu jeudi "
                  "matin, avec une bascule progressive sur les trois serveurs."),
            ("B", "De mon côté la procédure de retour arrière est prête, testée deux "
                  "fois hier après-midi sur l'environnement de préproduction."),
            ("A", "Très bien, nous partons donc sur jeudi matin, et je préviens les "
                  "utilisateurs concernés dès demain en début de journée."),
        ],
    ),
    # Le second bug du 25 août : « Ouais » a été promu prénom et s'est vu
    # attribuer treize minutes de temps de parole.
    "interjections": (
        DEUX_VOIX,
        [
            ("A", "Ouais, enfin, ça dépend vraiment de la charge du serveur au "
                  "moment précis où plusieurs personnes déposent leurs documents."),
            ("B", "Bon. Effectivement, le comportement change quand deux dépôts "
                  "arrivent en même temps, c'est ce que montrent les journaux."),
            ("A", "Voilà. Donc maintenant, la question devient de savoir si nous "
                  "corrigeons tout de suite ou si nous attendons la prochaine version."),
            ("B", "Écoute, franchement, je pense qu'il faut corriger maintenant, "
                  "parce que le problème touche déjà plusieurs utilisateurs."),
        ],
    ),
    # Une personne dit une seule phrase de toute la réunion. Le recollage
    # écarte les voix de moins de dix secondes : celle-ci doit être soit
    # rattachée correctement, soit honnêtement absente, jamais inventée.
    "voix-breve": (
        TROIS_VOIX,
        [
            ("A", "Nous commençons par le point sur la recette, qui nous occupe "
                  "depuis lundi et sur lequel il reste deux anomalies ouvertes."),
            ("B", "Les deux anomalies sont corrigées depuis hier soir, mais elles "
                  "attendent encore la validation de l'équipe fonctionnelle."),
            ("C", "Je confirme, tout est prêt de mon côté."),
            ("A", "Parfait, dans ce cas nous validons la recette et nous passons au "
                  "calendrier de mise en production de la semaine prochaine."),
            ("B", "Je prépare la note aux utilisateurs et je la fais relire avant "
                  "de l'envoyer, probablement demain en fin de matinée."),
        ],
    ),
    # Trois voix, avec auto-présentation pour deux d'entre elles seulement.
    # La troisième doit rester sans nom plutôt que d'hériter de celui d'un autre.
    "trois-voix": (
        TROIS_VOIX,
        [
            ("A", "Bonjour à tous, moi c'est Jacques, je vous propose de commencer "
                  "par le point sur la recette et les anomalies encore ouvertes."),
            ("B", "Merci Jacques. Moi c'est Amélie, je m'occupe de la partie "
                  "fonctionnelle, et j'ai relu l'ensemble des scénarios de test."),
            ("C", "De mon côté le déploiement en préproduction est terminé depuis "
                  "vendredi, sans aucun incident notable à signaler sur les serveurs."),
            ("A", "Merci Amélie pour la relecture. Il nous reste donc à valider les "
                  "deux derniers scénarios avant de lancer la mise en production."),
            ("C", "Je m'occupe de la bascule technique dès que vous me donnez le feu "
                  "vert, l'opération prend une vingtaine de minutes tout au plus."),
        ],
    ),
    # Le prénom de C n'est jamais prononcé par C : seul un renvoi bref, juste
    # après son unique tour, le lui attribue — un seul indice, trop peu pour
    # être affirmé, donc une proposition. `voix_a_nommer` écartait jusqu'ici
    # toute voix de moins de dix secondes, proposition comprise : la voix de C
    # ne dépasse jamais ce seuil sur toute la réunion.
    "proposition-breve": (
        TROIS_VOIX,
        [
            ("A", "Bonjour à tous, moi c'est Jacques, je vous propose de commencer "
                  "par le point sur la recette et les anomalies encore ouvertes."),
            ("B", "Merci Jacques. Moi c'est Amélie, je m'occupe de la partie "
                  "fonctionnelle, et j'ai relu l'ensemble des scénarios de test."),
            ("C", "Je confirme, tout est prêt de mon côté."),
            ("A", "Merci Kévin, on avance donc sur ce point-là et on passe à la "
                  "suite du calendrier de mise en production."),
            ("B", "Parfait, je prépare la note aux utilisateurs et je la fais "
                  "relire avant de l'envoyer, probablement demain en fin de matinée."),
        ],
    ),
    # Le même prénom pour un présent et pour un absent. L'outil doit proposer
    # plutôt qu'affirmer, et ne pas attribuer la voix au hasard.
    "homonymes": (
        DEUX_VOIX,
        [
            ("A", "Bonjour, moi c'est Jacques, et je précise tout de suite que "
                  "l'autre Jacques, celui du service financier, n'est pas parmi nous."),
            ("B", "Bien noté. Jacques du service financier nous enverra son avis par "
                  "écrit avant la fin de la semaine, il me l'a confirmé hier."),
            ("A", "Parfait. Alors nous avançons sans lui sur la partie technique, et "
                  "nous garderons la décision budgétaire pour la prochaine séance."),
            ("B", "Merci Jacques. Je note la répartition et je diffuse le relevé de "
                  "décisions à l'ensemble des participants dès cet après-midi."),
        ],
    ),
}


def main() -> int:
    lecteur = argparse.ArgumentParser(description=__doc__)
    lecteur.add_argument("dossier", type=Path, help="Où écrire les fichiers")
    lecteur.add_argument("--cas", choices=sorted(CAS), help="Un seul cas")
    arguments = lecteur.parse_args()

    voulus = [arguments.cas] if arguments.cas else sorted(CAS)
    arguments.dossier.mkdir(parents=True, exist_ok=True)
    for nom in voulus:
        voix, dialogue = CAS[nom]
        cible = arguments.dossier / f"cas-{nom}.wav"
        fabriquer(cible, voix=voix, dialogue=dialogue)
        taille = cible.stat().st_size / 1024
        print(f"  {cible.name:<26} {taille:6.0f} Ko  {len(dialogue)} répliques")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
