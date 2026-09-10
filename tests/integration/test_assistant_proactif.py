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

from greffier.adapters.configuration import Config
from greffier.wiring import assistant_of

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


def _assistant(material: str):
    config = Config()
    config.assistant.active = True
    # Sans voix : on éprouve ce qu'il décide de dire, pas la synthèse.
    config.assistant.voice = "aucun"
    lui = assistant_of(config, "essai-proactif")
    if lui is None or lui.cerveau is None:
        pytest.skip("aucun rédacteur configuré")
    lui.context = lambda: material
    return lui


def test_une_reunion_ordinaire_ne_lui_arrache_pas_un_mot():
    """Le cas de très loin le plus fréquent, et le plus facile à rater."""
    assert _assistant(ORDINAIRE).contribution(now=600.0) is None


def test_une_decision_sans_personne_pour_la_porter_le_fait_parler():
    opening = _assistant(SANS_RESPONSABLE).contribution(now=600.0)
    assert opening is not None
    assert "?" in opening.remark


def test_une_question_laissee_en_l_air_le_fait_parler():
    opening = _assistant(QUESTION_EN_L_AIR).contribution(now=600.0)
    assert opening is not None


def test_il_ne_cherche_rien_pendant_son_repos():
    """Un appel au modèle toutes les dix secondes pour un silence."""
    lui = _assistant(SANS_RESPONSABLE)
    lui.manners.parle_le = 590.0
    assert lui.contribution(now=600.0) is None


def test_ce_qu_il_dit_se_prononce(monkeypatch):
    """Ni titre, ni liste, ni adresse : tout cela serait lu à voix haute."""
    opening = _assistant(SANS_RESPONSABLE).contribution(now=600.0)
    assert opening is not None
    remark = opening.remark
    assert "\n" not in remark.strip()
    assert not remark.lstrip().startswith(("#", "-", "*", "|"))
    assert "http" not in remark
