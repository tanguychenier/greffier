"""Le fichier maître : ce qu'on garde, et dans quel ordre on le retrouve."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.adapters.store_files import FileStore
from greffier.domain.meeting import StoredMeeting, held_on
from greffier.domain.models import Span, SpeakerTurn, Utterance


def meeting(identifier: str) -> StoredMeeting:
    return StoredMeeting(
        identifier=identifier,
        audio=Path(f"/tmp/{identifier}.wav"),
        processed_at=datetime.now(UTC),
        duration=60.0,
        utterances=[Utterance(Span(0, 5), "Bonjour.")],
        turns=[SpeakerTurn(Span(0, 5), "1")],
        names={},
        propositions={},
        warnings=[],
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
        store = FileStore(tmp_path)
        for identifier in ("2026-09-02_17h37_reunion", "2026-09-09_10h05_reunion",
                            "2026-09-09_08h30_reunion"):
            store.record(meeting(identifier))
        assert store.lister() == [
            "2026-09-09_10h05_reunion",
            "2026-09-09_08h30_reunion",
            "2026-09-02_17h37_reunion",
        ]

    def test_un_identifiant_sans_date_ne_passe_pas_devant_une_reunion_datee(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("2026-09-09_10h05_reunion"))
        store.record(meeting("fausse-reunion"))
        assert store.lister()[0] == "2026-09-09_10h05_reunion"
        assert "fausse-reunion" in store.lister()

    def test_la_derniere_est_la_plus_recemment_tenue(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("zzz-essai"))
        store.record(meeting("2026-09-09_10h05_reunion"))
        latest = store.latest()
        assert latest is not None
        assert latest.identifier == "2026-09-09_10h05_reunion"

    def test_sans_dossier_la_liste_est_vide(self, tmp_path):
        assert FileStore(tmp_path / "rien").lister() == []


class TestHorodatageDeLIdentifiant:
    def test_la_date_et_l_heure_sont_lues(self):
        assert held_on("2026-09-09_10h05_reunion") == (2026, 9, 9, 10, 5)

    def test_une_date_sans_heure_reste_lisible(self):
        assert held_on("2026-09-09_reunion") == (2026, 9, 9, 0, 0)

    def test_un_identifiant_sans_date_ne_ment_pas(self):
        assert held_on("fausse-reunion") is None


class TestSujetChoisi:
    """Le sujet saisi à la main l'emporte sur le titre du compte rendu.

    Demandé à l'usage : la liste ne montrait que « 2026-09-09_10h05_reunion »
    tant qu'aucun compte rendu n'existait, et rien ne permettait de la nommer.
    """

    def test_le_sujet_survit_a_l_ecriture(self, tmp_path):
        store = FileStore(tmp_path)
        gardee = meeting("2026-09-09_10h05_reunion")
        gardee.subject = "Point Oasis"
        store.record(gardee)
        assert store.read("2026-09-09_10h05_reunion").subject == "Point Oasis"

    def test_sans_sujet_l_identifiant_nomme_la_reunion(self):
        assert meeting("2026-09-09_10h05_reunion").caption == "2026-09-09_10h05_reunion"

    def test_avec_un_sujet_c_est_lui_qui_nomme(self):
        gardee = meeting("2026-09-09_10h05_reunion")
        gardee.subject = "Point Oasis"
        assert gardee.caption == "Point Oasis"


class TestSuppression:
    def test_le_fichier_maitre_part(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("2026-09-09_10h05_reunion"))
        assert store.delete("2026-09-09_10h05_reunion") is True
        assert store.lister() == []

    def test_supprimer_ce_qui_n_existe_pas_le_dit(self, tmp_path):
        assert FileStore(tmp_path).delete("jamais-vue") is False


class TestAllerRetour:
    def test_ce_qui_est_ecrit_se_relit(self, tmp_path):
        store = FileStore(tmp_path)
        store.record(meeting("2026-09-09_10h05_reunion"))
        relue = store.read("2026-09-09_10h05_reunion")
        assert relue.utterances[0].text == "Bonjour."
        assert relue.turns[0].voice == "1"


def reunie(identifier: str = "2026-09-10_10h10_reunion") -> StoredMeeting:
    """Une réunion où deux voix ont été réunies sous le même nom."""
    detail = StoredMeeting(
        identifier=identifier,
        audio=Path(f"/tmp/{identifier}.wav"),
        processed_at=datetime.now(UTC),
        duration=60.0,
        utterances=[
            Utterance(Span(0, 5), "on cale la recette jeudi", voice="v1"),
            Utterance(Span(6, 11), "le devis part demain", voice="v2"),
        ],
        turns=[SpeakerTurn(Span(0, 5), "v1"), SpeakerTurn(Span(6, 11), "v2")],
        names={"v1": "Tanguy", "v2": "Paul"},
        propositions={},
        warnings=[],
    )
    detail.join_into("v2", "v1")
    return detail


class TestSeparerDeuxVoixApresLaReunion:
    """Réunir deux voix se défaisait dans le direct, et par rien ensuite.

    Le geste existait des deux côtés — nommer deux voix pareil les réunit, ce
    qui est exactement ce qu'il faut quand l'outil a découpé une personne en
    deux — mais seul le fil du direct savait revenir en arrière.
    """

    def test_la_voix_absorbee_reprend_ses_tours(self):
        detail = reunie()
        assert {t.voice for t in detail.turns} == {"v1"}
        assert detail.split("v1") is not None
        assert {t.voice for t in detail.turns} == {"v1", "v2"}

    def test_elle_reprend_ses_repliques(self):
        detail = reunie()
        detail.split("v1")
        par_voix = {u.voice for u in detail.utterances}
        assert par_voix == {"v1", "v2"}

    def test_elle_reprend_son_nom(self):
        detail = reunie()
        detail.split("v1")
        assert detail.names == {"v1": "Tanguy", "v2": "Paul"}

    def test_rien_a_separer_ne_casse_rien(self):
        detail = meeting("2026-09-10_11h00_reunion")
        assert detail.split("1") is None
        assert not detail.can_split("1")

    def test_la_fusion_se_dit_avant_de_la_defaire(self):
        detail = reunie()
        assert detail.can_split("v1")
        detail.split("v1")
        assert not detail.can_split("v1"), "une fois défaite, plus rien à défaire"

    def test_la_fusion_survit_a_l_ecriture(self, tmp_path):
        """Sans cela, séparer ne marche que tant que l'application est ouverte."""
        magasin = FileStore(tmp_path)
        magasin.record(reunie())
        relue = magasin.read("2026-09-10_10h10_reunion")
        assert relue.can_split("v1")
        assert relue.split("v1") is not None
        assert {t.voice for t in relue.turns} == {"v1", "v2"}

    def test_un_fichier_ecrit_avant_reste_lisible(self, tmp_path):
        """Aucune réunion déjà traitée ne doit devenir illisible."""
        import json

        magasin = FileStore(tmp_path)
        chemin = magasin.record(meeting("2026-09-09_10h05_reunion"))
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        del contenu["fusions"]
        chemin.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
        relue = magasin.read("2026-09-09_10h05_reunion")
        assert relue.joins == []
        assert not relue.can_split("1")

    def test_deux_fusions_se_defont_dans_l_ordre_inverse(self):
        detail = reunie()
        detail.utterances.append(Utterance(Span(12, 17), "et la prod lundi", voice="v3"))
        detail.turns.append(SpeakerTurn(Span(12, 17), "v3"))
        detail.names["v3"] = "Sophie"
        detail.join_into("v3", "v1")
        assert {t.voice for t in detail.turns} == {"v1"}
        detail.split("v1")
        assert "v3" in {t.voice for t in detail.turns}, "la dernière d'abord"
        assert "v2" not in {t.voice for t in detail.turns}
        detail.split("v1")
        assert {t.voice for t in detail.turns} == {"v1", "v2", "v3"}
