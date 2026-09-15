#!/usr/bin/env python3
"""Makes the meetings the chain has already got wrong.

`make_meeting.py` produces a clean meeting: two clear voices, first names
said in the three expected forms. It proves the chain works when all goes
well.

This file produces the opposite. Each case reproduces an error seen on a
real meeting, or a trap the design makes possible:

    absent            a first name mentioned designates somebody who is not there
    sans-reponse      somebody is called out and does not answer
    interjections     common words open sentences with a capital
    voix-breve        one person says only a few words in the whole meeting
    trois-voix        three speakers, two of them alike
    homonymes         a first name designates now somebody present, now somebody absent
    proposition-breve a short voice is named by a reference; the proposal must
                      not be lost with the fragment that carries it

    python3 tools/make_hard_cases.py output/            # all of them
    python3 tools/make_hard_cases.py output/ --case absent

The case names are the ones the tests and the recordings carry, in French.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_meeting import make  # noqa: E402

# Clearly distinct voices, so that the test measures the chain and not the
# ability of the speech synthesis to make two different timbres.
THREE_VOICES = {"A": "Jacques", "B": "Amélie", "C": "Grandpa (Français (France))"}
TWO_VOICES = {"A": "Jacques", "B": "Amélie"}

# Every line lasts more than three seconds: under that, a voiceprint does not
# carry enough voice to be usable.
CASES: dict[str, tuple[dict, list[tuple[str, str]]]] = {
    # Lise is mentioned six times and never speaks. She must appear nowhere
    # as an attendee. The minutes of a real meeting had handled this case
    # correctly; it serves as a non-regression.
    "absent": (
        TWO_VOICES,
        [
            ("A", "Lise nous a envoyé son retour hier soir par courriel, et elle "
                  "soulève un point que nous avions complètement laissé de côté."),
            ("B", "Oui, j'ai lu le message de Lise ce matin. Elle a raison sur le "
                  "fond, il faut reprendre cette partie avant la mise en production."),
            ("A", "Lise revient de congé le premier septembre, donc nous attendrons "
                  "son retour avant de trancher définitivement sur ce sujet."),
            ("B", "D'accord. Je note que rien ne bouge avant que Lise ait pu relire "
                  "l'ensemble du dossier et donner son accord formel."),
        ],
    ),
    # The bug of 25 August: somebody is called out, that person does not
    # answer, and their first name sticks to the voice that speaks next.
    "sans-reponse": (
        TWO_VOICES,
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
    # The second bug of 25 August: "Ouais" was promoted to a first name and
    # given thirteen minutes of speaking time.
    "interjections": (
        TWO_VOICES,
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
    # One person says a single sentence in the whole meeting. The stitching
    # sets aside voices under ten seconds: this one must be either attached
    # correctly, or honestly absent, never invented.
    "voix-breve": (
        THREE_VOICES,
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
    # Three voices, with a self-introduction for two of them only. The third
    # must stay unnamed rather than inherit somebody else's name.
    "trois-voix": (
        THREE_VOICES,
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
    # C's first name is never said by C: only a brief reference, right after
    # their single turn, gives it to them, a single clue, too little to be
    # asserted, hence a proposal. `voix_a_nommer` used to set aside every
    # voice under ten seconds, proposal included: C's voice never passes that
    # threshold in the whole meeting.
    "proposition-breve": (
        THREE_VOICES,
        [
            ("A", "Bonjour à tous, moi c'est Jacques, je vous propose de commencer "
                  "par le point sur la recette et les anomalies encore ouvertes."),
            ("B", "Merci Jacques. Moi c'est Amélie, je m'occupe de la partie "
                  "fonctionnelle, et j'ai relu l'ensemble des scénarios de test."),
            ("C", "Je confirme, tout est prêt de mon côté."),
            ("A", "Merci Kilian, on avance donc sur ce point-là et on passe à la "
                  "suite du calendrier de mise en production."),
            ("B", "Parfait, je prépare la note aux utilisateurs et je la fais "
                  "relire avant de l'envoyer, probablement demain en fin de matinée."),
        ],
    ),
    # The same first name for somebody present and somebody absent. The tool
    # must propose rather than assert, and not give the voice at random.
    "homonymes": (
        TWO_VOICES,
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Where to write the files")
    parser.add_argument("--case", choices=sorted(CASES), help="One case only")
    arguments = parser.parse_args()

    wanted = [arguments.case] if arguments.case else sorted(CASES)
    arguments.folder.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        voice, dialogue = CASES[name]
        target = arguments.folder / f"cas-{name}.wav"
        make(target, voice=voice, dialogue=dialogue)
        size = target.stat().st_size / 1024
        print(f"  {target.name:<26} {size:6.0f} KB  {len(dialogue)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
