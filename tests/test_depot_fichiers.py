"""Le fichier maître : ce qu'on garde, et dans quel ordre on le retrouve."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.adaptateurs.depot_fichiers import DepotFichiers
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole
from greffier.domaine.reunion import ReunionEnregistree, tenue_le


def reunion(identifiant: str) -> ReunionEnregistree:
    return ReunionEnregistree(
        identifiant=identifiant,
        audio=Path(f"/tmp/{identifiant}.wav"),
        traitee_le=datetime.now(UTC),
        duree=60.0,
        repliques=[Replique(Intervalle(0, 5), "Bonjour.")],
        tours=[TourDeParole(Intervalle(0, 5), "1")],
        noms={},
        propositions={},
        avertissements=[],
    )


class TestOrdreDesReunions:
    """« La dernière réunion » doit être la dernière **tenue**.

    Le tri était alphabétique inversé, ce qui marche tant que tout identifiant
    commence par sa date. Le 2026-09-09, « fausse-reunion » — une réunion
    d'essai — passait avant « 2026-09-09_10h05_reunion » parce que « f » vient
    après « 2 » : « greffier rediger » sans argument a rédigé le compte rendu
    de la mauvaise réunion, et « greffier envoyer » l'aurait expédié.
    """

    def test_les_reunions_datees_vont_de_la_plus_recente_a_la_plus_ancienne(self, tmp_path):
        depot = DepotFichiers(tmp_path)
        for identifiant in ("2026-09-02_17h37_reunion", "2026-09-09_10h05_reunion",
                            "2026-09-09_08h30_reunion"):
            depot.enregistrer(reunion(identifiant))
        assert depot.lister() == [
            "2026-09-09_10h05_reunion",
            "2026-09-09_08h30_reunion",
            "2026-09-02_17h37_reunion",
        ]

    def test_un_identifiant_sans_date_ne_passe_pas_devant_une_reunion_datee(self, tmp_path):
        depot = DepotFichiers(tmp_path)
        depot.enregistrer(reunion("2026-09-09_10h05_reunion"))
        depot.enregistrer(reunion("fausse-reunion"))
        assert depot.lister()[0] == "2026-09-09_10h05_reunion"
        assert "fausse-reunion" in depot.lister()

    def test_la_derniere_est_la_plus_recemment_tenue(self, tmp_path):
        depot = DepotFichiers(tmp_path)
        depot.enregistrer(reunion("zzz-essai"))
        depot.enregistrer(reunion("2026-09-09_10h05_reunion"))
        derniere = depot.derniere()
        assert derniere is not None
        assert derniere.identifiant == "2026-09-09_10h05_reunion"

    def test_sans_dossier_la_liste_est_vide(self, tmp_path):
        assert DepotFichiers(tmp_path / "rien").lister() == []


class TestHorodatageDeLIdentifiant:
    def test_la_date_et_l_heure_sont_lues(self):
        assert tenue_le("2026-09-09_10h05_reunion") == (2026, 9, 9, 10, 5)

    def test_une_date_sans_heure_reste_lisible(self):
        assert tenue_le("2026-09-09_reunion") == (2026, 9, 9, 0, 0)

    def test_un_identifiant_sans_date_ne_ment_pas(self):
        assert tenue_le("fausse-reunion") is None


class TestAllerRetour:
    def test_ce_qui_est_ecrit_se_relit(self, tmp_path):
        depot = DepotFichiers(tmp_path)
        depot.enregistrer(reunion("2026-09-09_10h05_reunion"))
        relue = depot.lire("2026-09-09_10h05_reunion")
        assert relue.repliques[0].texte == "Bonjour."
        assert relue.tours[0].voix == "1"
