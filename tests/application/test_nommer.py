"""`voix_a_nommer` : quelles voix proposer à l'utilisateur, et lesquelles taire."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.application.nommer import voix_a_nommer
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole
from greffier.domaine.reunion import ReunionEnregistree


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


class DepotFactice:
    def __init__(self, reunion):
        self.reunion = reunion
        self.ecritures = 0

    def lire(self, _identifiant):
        return self.reunion

    def enregistrer(self, reunion):
        self.reunion = reunion
        self.ecritures += 1


class BanqueFactice:
    def __init__(self):
        self.ajouts = []

    def personnes(self):
        return []

    def enregistrer(self, nom, empreinte):
        self.ajouts.append(nom)


class ExtracteurFactice:
    def extraire_intervalles(self, _audio, intervalles):
        from greffier.domaine.empreintes import normaliser

        return [normaliser([1.0, 0.0], duree_source=i.duree) for i in intervalles]


def nommage_factice(reunion):
    from greffier.application.nommer import Nommage

    depot = DepotFactice(reunion)
    return Nommage(depot=depot, banque=BanqueFactice(), extracteur=ExtracteurFactice())


class TestNommerReunitLesVoix:
    def test_deux_voix_du_meme_prenom_deviennent_une(self):
        """Le geste qu'on fait sans le savoir.

        Nommer « Michel » une deuxième voix, c'est dire qu'elle est de Michel,
        donc de la même personne. Sans réunion, le compte rendu annonçait deux
        Michel, et une réunion réelle a demandé trente-six nommages à la main
        pour trois personnes présentes.
        """
        reunion = reunion_type(
            repliques=[Replique(Intervalle(0, 40), "bonjour", "1"),
                       Replique(Intervalle(60, 80), "oui", "2")],
            tours=[TourDeParole(Intervalle(0, 40), "1"),
                   TourDeParole(Intervalle(60, 80), "2")],
            noms={"1": "Michel"},
        )
        nommage = nommage_factice(reunion)
        rendu = nommage.nommer("2026-08-24_reunion", "2", "Michel")
        assert list(rendu.noms.values()) == ["Michel"]
        assert len(set(t.voix for t in rendu.tours)) == 1

    def test_la_voix_la_plus_fournie_garde_son_identifiant(self):
        """C'est son extrait qu'on réécoutera : autant que ce soit le plus long."""
        reunion = reunion_type(
            repliques=[Replique(Intervalle(0, 5), "oui", "petite"),
                       Replique(Intervalle(10, 90), "un long propos", "grande")],
            tours=[TourDeParole(Intervalle(0, 5), "petite"),
                   TourDeParole(Intervalle(10, 90), "grande")],
            noms={"grande": "Michel"},
        )
        rendu = nommage_factice(reunion).nommer("2026-08-24_reunion", "petite", "Michel")
        assert set(rendu.noms) == {"grande"}

    def test_la_casse_ne_cree_pas_deux_personnes(self):
        reunion = reunion_type(
            repliques=[Replique(Intervalle(0, 40), "a", "1"),
                       Replique(Intervalle(60, 80), "b", "2")],
            tours=[TourDeParole(Intervalle(0, 40), "1"),
                   TourDeParole(Intervalle(60, 80), "2")],
            noms={"1": "Michel"},
        )
        rendu = nommage_factice(reunion).nommer("2026-08-24_reunion", "2", "michel")
        assert list(rendu.noms.values()) == ["Michel"]


class TestNommerRefuseCeQuiNEnEstPas:
    def test_le_libelle_de_l_interface_n_entre_pas_en_banque(self):
        """La banque du poste portait « A nommer ». Plus jamais."""
        import pytest

        nommage = nommage_factice(reunion_type())
        with pytest.raises(ValueError, match="pas un prénom"):
            nommage.nommer("2026-08-24_reunion", "1", "A nommer")

    def test_rien_n_est_verse_en_banque_quand_le_nom_est_refuse(self):
        import pytest

        reunion = reunion_type()
        nommage = nommage_factice(reunion)
        with pytest.raises(ValueError):
            nommage.nommer("2026-08-24_reunion", "1", "?")
        assert nommage.banque.ajouts == []


class TestOublier:
    def test_un_nom_pose_par_erreur_se_retire(self):
        """Le geste le plus coûteux de l'outil n'était pas défaisable."""
        reunion = reunion_type(noms={"1": "Michel"})
        rendu = nommage_factice(reunion).oublier("2026-08-24_reunion", "1")
        assert rendu.noms == {}

    def test_oublier_une_voix_sans_nom_le_dit(self):
        import pytest

        with pytest.raises(KeyError):
            nommage_factice(reunion_type()).oublier("2026-08-24_reunion", "1")

    def test_une_proposition_s_oublie_aussi(self):
        reunion = reunion_type(propositions={"1": "Kévin"})
        rendu = nommage_factice(reunion).oublier("2026-08-24_reunion", "1")
        assert rendu.propositions == {}
