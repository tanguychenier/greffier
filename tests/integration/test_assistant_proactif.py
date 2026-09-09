"""L'assistant intervient quand il faut, et se tait le reste du temps.

La moitié difficile est le silence. Un modèle à qui l'on demande « as-tu quelque
chose à dire » trouve toujours quelque chose à dire, et un assistant qui
commente chaque tranche d'une réunion est retiré au bout de dix minutes. Ces
cas mesurent donc les deux faces : ce qu'il doit relever, et ce qu'il doit
laisser passer.

Ces tests appellent le vrai rédacteur, donc le réseau et le quota. Ils sont
passés à la main avant une démonstration, pas à chaque commit.
"""

from __future__ import annotations

import pytest

from greffier.adaptateurs.configuration import Config
from greffier.composition import participant

pytestmark = pytest.mark.lent

ORDINAIRE = """Camille : le déploiement en préproduction s'est bien passé vendredi.
Dominique : j'ai relu la documentation, elle est à jour.
Camille : très bien. On enchaîne sur le point suivant.
Dominique : d'accord.
"""

SANS_RESPONSABLE = """Camille : donc on est d'accord, on migre la base en Symfony 7
avant la recette.
Dominique : oui, c'est acté.
Camille : parfait. Sujet suivant, les congés d'été.
"""

QUESTION_EN_L_AIR = """Dominique : est-ce que quelqu'un sait si les flux sont ouverts
vers la préproduction du client ?
Camille : bon, sinon, il faut qu'on parle du budget du trimestre.
Dominique : oui, on a un dépassement de douze pour cent.
"""


def _assistant(matiere: str):
    config = Config()
    config.assistant.actif = True
    # Sans voix : on éprouve ce qu'il décide de dire, pas la synthèse.
    config.assistant.voix = "aucun"
    lui = participant(config, "essai-proactif")
    if lui is None or lui.cerveau is None:
        pytest.skip("aucun rédacteur configuré")
    lui.contexte = lambda: matiere
    return lui


def test_une_reunion_ordinaire_ne_lui_arrache_pas_un_mot():
    """Le cas de très loin le plus fréquent, et le plus facile à rater."""
    assert _assistant(ORDINAIRE).apport(maintenant=600.0) is None


def test_une_decision_sans_personne_pour_la_porter_le_fait_parler():
    occasion = _assistant(SANS_RESPONSABLE).apport(maintenant=600.0)
    assert occasion is not None
    assert "?" in occasion.propos


def test_une_question_laissee_en_l_air_le_fait_parler():
    occasion = _assistant(QUESTION_EN_L_AIR).apport(maintenant=600.0)
    assert occasion is not None


def test_il_ne_cherche_rien_pendant_son_repos():
    """Un appel au modèle toutes les dix secondes pour un silence."""
    lui = _assistant(SANS_RESPONSABLE)
    lui.politique.parle_le = 590.0
    assert lui.apport(maintenant=600.0) is None


def test_ce_qu_il_dit_se_prononce(monkeypatch):
    """Ni titre, ni liste, ni adresse : tout cela serait lu à voix haute."""
    occasion = _assistant(SANS_RESPONSABLE).apport(maintenant=600.0)
    assert occasion is not None
    propos = occasion.propos
    assert "\n" not in propos.strip()
    assert not propos.lstrip().startswith(("#", "-", "*", "|"))
    assert "http" not in propos
