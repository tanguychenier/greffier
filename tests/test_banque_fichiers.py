"""La banque de voix sur le disque, et le fichier maître d'une réunion."""

import json
from datetime import UTC, datetime

import pytest

from greffier.adaptateurs.banque_fichiers import BanqueFichiers, _fichier_sur
from greffier.adaptateurs.depot_fichiers import FORMAT, DepotFichiers, ReunionEnregistree
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
        """Et un fichier qui n'appartient qu'à lui.

        Ce test attendait « sans-nom », qui était le défaut même : tous les noms
        sans lettre ASCII rendaient cette valeur, donc le même fichier, donc une
        seule personne pour plusieurs. L'intention tenait, l'assertion la
        trahissait.
        """
        assert _fichier_sur("???")
        assert _fichier_sur("???") != _fichier_sur("!!!")

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
        """Mieux vaut refuser que lire de travers un fichier d'une version future.

        Le numéro est lu depuis le module et non écrit en dur : la version
        précédente cherchait « "format": 1 » dans le texte, si bien que passer
        au format 2 ne cassait pas le test — il ne remplaçait plus rien et
        vérifiait qu'un fichier valide lève une erreur, ce qu'il ne fait pas.
        """
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type())
        chemin = tmp_path / "2026-08-24_reunion.json"
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        contenu["format"] = FORMAT + 1
        chemin.write_text(json.dumps(contenu), encoding="utf-8")
        with pytest.raises(ValueError, match="plus récente"):
            magasin.lire("2026-08-24_reunion")

    def test_un_fichier_sans_les_heures_se_relit(self, tmp_path):
        """Le format 1 ne portait pas les heures d'horloge : il reste lisible.

        Les réunions déjà sur le disque n'ont pas à être retraitées pour que
        l'outil sache encore les ouvrir.
        """
        magasin = DepotFichiers(tmp_path)
        magasin.enregistrer(reunion_type())
        chemin = tmp_path / "2026-08-24_reunion.json"
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        contenu["format"] = 1
        del contenu["commencee_le"]
        del contenu["terminee_le"]
        chemin.write_text(json.dumps(contenu), encoding="utf-8")
        relue = magasin.lire("2026-08-24_reunion")
        assert relue.commencee_le is None
        assert relue.terminee_le is None
        assert relue.repliques, "le reste du fichier se lit normalement"

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


class TestNomsNonLatins:
    """Deux personnes doivent rester deux personnes.

    La réduction en ASCII n'a aucune lettre à garder d'un nom cyrillique, grec,
    arabe ou idéographique. Le repli sur « sans-nom » les rangeait toutes dans
    le même fichier d'empreintes : ce n'est pas de l'affichage, c'est une fusion
    de données, dans le fichier même qui doit les tenir séparées. Atteignable
    dès aujourd'hui par un nom saisi à la main dans l'onglet Voix.
    """

    def test_deux_noms_non_latins_restent_deux_fichiers(self, banque):
        banque.enregistrer("Дмитрий", voix(1.0, 0.0))
        banque.enregistrer("Ольга", voix(0.0, 1.0))

        assert len(list(banque.dossier.glob("*.json"))) == 2

    def test_chacun_se_relit_sous_son_propre_nom(self, banque):
        banque.enregistrer("田中", voix(1.0, 0.0))
        banque.enregistrer("佐藤", voix(0.0, 1.0))

        assert {p.nom for p in banque.personnes()} == {"田中", "佐藤"}

    def test_leurs_empreintes_ne_se_melangent_pas(self, banque):
        """La fusion était silencieuse : deux voix dans un seul dossier."""
        banque.enregistrer("Δημήτρης", voix(1.0, 0.0))
        banque.enregistrer("محمد", voix(0.0, 1.0))

        assert all(len(p.empreintes) == 1 for p in banque.personnes())

    def test_un_nom_latin_garde_son_fichier_lisible(self, banque):
        """La correction ne doit pas rendre illisibles les noms qui allaient bien."""
        banque.enregistrer("Josiane", voix(1.0, 0.0))

        assert (banque.dossier / "josiane.json").is_file()


class TestReparerUneBanque:
    """Corriger au grain de l'empreinte, et non de la personne."""

    def test_une_empreinte_se_retire_sans_perdre_les_autres(self, tmp_path):
        """Effacer quelqu'un pour une empreinte fautive perd tout le reste.

        Ce qui décide de la reconnaissance est l'empreinte : c'est donc à ce
        grain qu'on doit pouvoir corriger.
        """
        banque = BanqueFichiers(tmp_path)
        for vecteur in ([1.0, 0.0], [0.0, 1.0], [0.5, 0.5]):
            banque.enregistrer("Paul", normaliser(vecteur, duree_source=10.0))
        assert banque.retirer_empreintes("Paul", [1]) == 1
        reste = banque.trouver("Paul")
        assert reste is not None and len(reste.empreintes) == 2

    def test_tout_retirer_efface_la_personne(self, tmp_path):
        """Une entrée sans empreinte ne reconnaît rien et encombre la liste."""
        banque = BanqueFichiers(tmp_path)
        banque.enregistrer("Paul", normaliser([1.0, 0.0], duree_source=10.0))
        assert banque.retirer_empreintes("Paul", [0]) == 1
        assert banque.trouver("Paul") is None

    def test_un_rang_hors_limite_ne_casse_rien(self, tmp_path):
        banque = BanqueFichiers(tmp_path)
        banque.enregistrer("Paul", normaliser([1.0, 0.0], duree_source=10.0))
        assert banque.retirer_empreintes("Paul", [7]) == 0
        assert banque.trouver("Paul") is not None

    def test_une_personne_inconnue_ne_leve_pas(self, tmp_path):
        assert BanqueFichiers(tmp_path).retirer_empreintes("Absent", [0]) == 0


class TestOublierUneReunion:
    """Le geste qui manquait : défaire ce qu'une réunion a versé."""

    def test_les_empreintes_d_une_reunion_partent_de_partout(self, tmp_path):
        """Une réunion mal attribuée verse sous plusieurs noms d'un coup.

        Sur ce poste, il a fallu lire les durées — treize et trente et une
        minutes — pour comprendre que deux empreintes de « Paul » venaient
        d'une réunion où il n'était pas.
        """
        from dataclasses import replace

        banque = BanqueFichiers(tmp_path)
        bonne = normaliser([1.0, 0.0], duree_source=10.0)
        fautive = replace(normaliser([0.0, 1.0], duree_source=900.0),
                          origine="2026-09-09_reunion")
        banque.enregistrer("Paul", bonne)
        banque.enregistrer("Paul", fautive)
        banque.enregistrer("Kevin", fautive)

        retires = banque.oublier_une_reunion("2026-09-09_reunion")

        assert retires == {"Paul": 1, "Kevin": 1}
        paul = banque.trouver("Paul")
        assert paul is not None and len(paul.empreintes) == 1
        # Kevin n'avait que celle-là : il disparaît plutôt que de rester vide.
        assert banque.trouver("Kevin") is None

    def test_une_reunion_inconnue_ne_touche_a_rien(self, tmp_path):
        banque = BanqueFichiers(tmp_path)
        banque.enregistrer("Paul", normaliser([1.0, 0.0], duree_source=10.0))
        assert banque.oublier_une_reunion("jamais-tenue") == {}
        assert banque.trouver("Paul") is not None

    def test_l_origine_survit_a_l_ecriture(self, tmp_path):
        """Sans persistance, la trace ne servirait qu'au processus qui l'a posée."""
        from dataclasses import replace

        banque = BanqueFichiers(tmp_path)
        banque.enregistrer("Paul", replace(
            normaliser([1.0, 0.0], duree_source=10.0), origine="2026-09-09_reunion"))
        relue = BanqueFichiers(tmp_path).trouver("Paul")
        assert relue is not None
        assert relue.empreintes[0].origine == "2026-09-09_reunion"
