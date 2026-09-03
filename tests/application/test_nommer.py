"""`voix_a_nommer` : quelles voix proposer à l'utilisateur, et lesquelles taire."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.adaptateurs.depot_fichiers import ReunionEnregistree
from greffier.application.nommer import voix_a_nommer
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole


def reunion_type(**remplacements) -> ReunionEnregistree:
    defauts = dict(
        identifiant="2026-08-24_reunion",
        audio=Path("/tmp/r.wav"),
        traitee_le=datetime.now(UTC),
        duree=100.0,
        repliques=[Replique(Intervalle(0, 40), "bonjour à tous", "1"),
                   Replique(Intervalle(60, 65), "bref", "2")],
        tours=[TourDeParole(Intervalle(0, 40), "1"), TourDeParole(Intervalle(60, 65), "2")],
        noms={},
        propositions={},
        avertissements=[],
    )
    defauts.update(remplacements)
    return ReunionEnregistree(**defauts)


class TestVoixANommer:
    def test_une_voix_courte_sans_indice_reste_ecartee(self):
        """Le comportement d'origine, préservé : un fragment sans rien pour le
        rattacher ne doit pas passer pour un participant."""
        reunion = reunion_type()
        assert "2" not in {v.voix for v in voix_a_nommer(reunion)}

    def test_une_proposition_sur_une_voix_courte_n_est_pas_perdue(self):
        """Le défaut corrigé : un prénom détecté dans une réponse brève doit
        survivre au filtre de durée, sans quoi il ne s'affiche jamais."""
        reunion = reunion_type(propositions={"2": "Kévin"})
        entree = next(v for v in voix_a_nommer(reunion) if v.voix == "2")
        assert entree.proposition == "Kévin"
        assert entree.a_nommer

    def test_un_nom_deja_attribue_sur_une_voix_courte_n_est_pas_perdu(self):
        reunion = reunion_type(noms={"2": "Kévin"})
        entree = next(v for v in voix_a_nommer(reunion) if v.voix == "2")
        assert entree.nom == "Kévin"
        assert not entree.a_nommer

    def test_une_voix_longue_reste_toujours_proposee(self):
        reunion = reunion_type()
        assert "1" in {v.voix for v in voix_a_nommer(reunion)}

    def test_la_part_relative_ignore_les_voix_courtes_reintroduites(self):
        """Réintroduire une voix courte ne doit pas diluer la part de celles
        qui dépassent déjà le seuil de matière."""
        reunion = reunion_type(propositions={"2": "Kévin"})
        longue = next(v for v in voix_a_nommer(reunion) if v.voix == "1")
        assert longue.part == 1.0
