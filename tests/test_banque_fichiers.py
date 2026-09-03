"""La banque de voix sur le disque, et le fichier maître d'une réunion."""

import json
from datetime import UTC, datetime

import pytest

from greffier.adaptateurs.banque_fichiers import BanqueFichiers, _fichier_sur
from greffier.adaptateurs.depot_fichiers import DepotFichiers, ReunionEnregistree
from greffier.domaine.empreintes import normaliser, reconnaitre
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole


def voix(*composantes, duree=10.0):
    return normaliser(composantes, duree_source=duree)


@pytest.fixture
def banque(tmp_path):
    return BanqueFichiers(tmp_path / "banque-de-voix")


class TestBanqueDeVoix:
    def test_une_voix_enregistree_est_relue(self, banque):
        banque.enregistrer("Josiane", voix(1.0, 0.0, 0.0))
        personnes = banque.personnes()
        assert [p.nom for p in personnes] == ["Josiane"]
        assert len(personnes[0].empreintes) == 1

    def test_la_reconnaissance_traverse_le_disque(self, banque):
        """Le vrai but : reconnue d'une réunion à l'autre."""
        banque.enregistrer("Josiane", voix(1.0, 0.02, 0.0))
        banque.enregistrer("Marc", voix(0.0, 0.0, 1.0))
        trouve = reconnaitre(voix(0.99, 0.05, 0.0), banque.personnes())
        assert trouve is not None and trouve.nom == "Josiane"

    def test_les_empreintes_s_accumulent_pour_une_meme_personne(self, banque):
        for i in range(3):
            banque.enregistrer("Josiane", voix(1.0, i / 10, 0.0))
        assert len(banque.trouver("Josiane").empreintes) == 3

    def test_l_accumulation_reste_bornee(self, tmp_path):
        banque = BanqueFichiers(tmp_path / "b", maximum=2)
        for i in range(6):
            banque.enregistrer("Josiane", voix(1.0, 0.0, duree=float(i)))
        assert len(banque.trouver("Josiane").empreintes) == 2

    def test_les_accents_ne_creent_pas_deux_personnes(self):
        """Les systèmes de fichiers ne normalisent pas les accents pareil."""
        assert _fichier_sur("Rémi Kaës") == _fichier_sur("Remi Kaes")

    def test_un_nom_exotique_donne_quand_meme_un_fichier(self):
        assert _fichier_sur("???") == "sans-nom"

    def test_renommer_conserve_les_empreintes(self, banque):
        banque.enregistrer("Josianne", voix(1.0, 0.0))
        banque.renommer("Josianne", "Josiane")
        assert banque.trouver("Josianne") is None
        assert len(banque.trouver("Josiane").empreintes) == 1

    def test_fusionner_reunit_deux_entrees(self, banque):
        banque.enregistrer("Josiane", voix(1.0, 0.0))
        banque.enregistrer("Josiane B", voix(0.9, 0.1))
        fusionnee = banque.fusionner("Josiane", "Josiane B")
        assert len(fusionnee.empreintes) == 2
        assert banque.trouver("Josiane B") is None

    def test_oublier_efface_vraiment(self, banque):
        """Donnée biométrique : la suppression doit être simple et complète."""
        banque.enregistrer("Josiane", voix(1.0, 0.0))
        assert banque.oublier("Josiane") is True
        assert banque.personnes() == []
        assert banque.oublier("Josiane") is False

    def test_un_fichier_abime_n_empeche_pas_de_lire_les_autres(self, banque):
        banque.enregistrer("Josiane", voix(1.0, 0.0))
        (banque.dossier / "casse.json").write_text("{ pas du json", encoding="utf-8")
        assert [p.nom for p in banque.personnes()] == ["Josiane"]

    def test_une_banque_absente_n_est_pas_une_erreur(self, tmp_path):
        assert BanqueFichiers(tmp_path / "jamais-creee").personnes() == []


def reunion_type(**remplacements):
    defauts = dict(
        identifiant="2026-08-24_reunion",
        audio=__import__("pathlib").Path("/tmp/r.wav"),
        traitee_le=datetime.now(UTC),
        duree=100.0,
        repliques=[Replique(Intervalle(0, 40), "bonjour à tous", "1"),
                   Replique(Intervalle(60, 95), "au revoir", "2")],
        tours=[TourDeParole(Intervalle(0, 40), "1"), TourDeParole(Intervalle(60, 95), "2")],
        noms={"1": "Josiane"},
        propositions={"2": "Marc"},
        avertissements=[],
    )
    defauts.update(remplacements)
    return ReunionEnregistree(**defauts)


class TestFichierMaitre:
    def test_ce_qui_est_ecrit_est_relu_identique(self, tmp_path):
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type())
        relue = magasin.lire("2026-08-24_reunion")
        assert relue.noms == {"1": "Josiane"}
        assert relue.propositions == {"2": "Marc"}
        assert [r.texte for r in relue.repliques] == ["bonjour à tous", "au revoir"]
        assert relue.repliques[0].intervalle.fin == 40

    def test_les_horodatages_survivent(self, tmp_path):
        """Ils permettent de citer un passage et d'y revenir."""
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type())
        assert magasin.lire("2026-08-24_reunion").tours[1].intervalle.debut == 60

    def test_la_couverture_revele_ce_qui_manque(self):
        """75 s de texte sur 100 s d'audio : un quart n'a pas été transcrit."""
        assert reunion_type().couverture == pytest.approx(0.75)

    def test_les_trous_sont_listes(self):
        trous = reunion_type().trous(minimum=5.0)
        assert [(t.debut, t.fin) for t in trous] == [(40.0, 60.0), (95.0, 100.0)]

    def test_un_petit_silence_n_est_pas_un_trou(self):
        assert reunion_type().trous(minimum=30.0) == []

    def test_une_reunion_inconnue_le_dit_clairement(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="inconnue"):
            DepotFichiers(tmp_path).lire("jamais-vue")

    def test_un_format_plus_recent_est_refuse(self, tmp_path):
        """Mieux vaut refuser que lire de travers un fichier d'une version future."""
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type())
        chemin = tmp_path / "2026-08-24_reunion.json"
        chemin.write_text(chemin.read_text().replace('"format": 1', '"format": 99'))
        with pytest.raises(ValueError, match="plus récente"):
            magasin.lire("2026-08-24_reunion")

    def test_les_plus_recentes_d_abord(self, tmp_path):
        magasin = DepotFichiers(tmp_path)
        for identifiant in ("2026-08-01_a", "2026-08-24_b", "2026-08-12_c"):
            magasin.enregistrer(reunion_type(identifiant=identifiant))
        assert magasin.lister()[0] == "2026-08-24_b"

    def test_les_evenements_materiel_survivent(self, tmp_path):
        """Nécessaire pour régénérer la rédaction plus tard sans perdre ce que
        la veille du matériel avait constaté."""
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type(
            evenements_materiel=["casque branché à 12:03"]
        ))
        relue = magasin.lire("2026-08-24_reunion")
        assert relue.evenements_materiel == ["casque branché à 12:03"]

    def test_un_fichier_maitre_sans_evenements_materiel_se_relit(self, tmp_path):
        """Un fichier maître écrit avant l'ajout de ce champ n'a pas la clé :
        elle doit se relire vide, pas planter."""
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type())
        chemin = tmp_path / "2026-08-24_reunion.json"
        contenu = json.loads(chemin.read_text())
        del contenu["evenements_materiel"]
        chemin.write_text(json.dumps(contenu))
        assert magasin.lire("2026-08-24_reunion").evenements_materiel == []
