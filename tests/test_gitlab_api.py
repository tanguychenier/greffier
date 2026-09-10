"""Lire et écrire sur un GitLab inscrit, et refuser le reste."""

import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import gitlab_api
from greffier.domain.sources import Kind, Right, Source


def source(droit: Right = Right.LECTURE) -> Source:
    return Source(
        name="recherche", kind=Kind.GITLAB,
        adresse="https://gitlab.example.fr", projet="equipe/outil",
        droit=droit, token="GREFFIER_GITLAB_JETON",
    )


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeGitLab:
    """Un GitLab qui garde ce qu'on lui envoie : l'adresse et le corps comptent."""

    def __init__(self) -> None:
        self.appels: list = []
        self.charge: object = []

    def __call__(self, requete, timeout=None):
        self.appels.append(requete)
        return Response(json.dumps(self.charge).encode("utf-8"))

    @property
    def premier(self):
        return self.appels[0]


@pytest.fixture
def gitlab(monkeypatch) -> FakeGitLab:
    faux = FakeGitLab()
    monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", faux)
    return faux


@pytest.fixture
def muet(monkeypatch):
    """Aucun appel ne doit partir : le refus se décide avant le réseau."""
    def jamais(*_args, **_options):
        raise AssertionError("aucun appel ne devait partir")

    monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", jamais)


def echouer(monkeypatch, code: int) -> None:
    def tomber(*_args, **_options):
        raise urllib.error.HTTPError(
            "https://x", code, "non", {}, BytesIO(b'{"message":"non"}')  # type: ignore[arg-type]
        )

    monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", tomber)


UN_TICKET = {
    "iid": 42, "title": "Corriger l'envoi", "state": "opened",
    "web_url": "https://gitlab.example.fr/equipe/outil/-/issues/42",
    "assignee": {"name": "Sophie"}, "labels": ["recette"],
}


class TestLecture:
    def test_les_tickets_sont_rendus_utilisables(self, gitlab):
        gitlab.charge = [UN_TICKET]
        trouves = gitlab_api.tickets(source(), "glpat-x")
        assert trouves[0].number == 42
        assert trouves[0].assigne == "Sophie"
        assert trouves[0].etiquettes == ("recette",)

    def test_un_ticket_sans_assigne_ne_casse_pas(self, gitlab):
        """GitLab rend « assignee: null », pas un objet vide."""
        gitlab.charge = [{**UN_TICKET, "assignee": None}]
        assert gitlab_api.tickets(source(), "glpat-x")[0].assigne == ""

    def test_la_ligne_montre_le_ticket_d_un_coup(self, gitlab):
        gitlab.charge = [UN_TICKET]
        dit = gitlab_api.tickets(source(), "glpat-x")[0].say()
        assert "#42" in dit and "Sophie" in dit and "recette" in dit

    def test_le_projet_du_registre_borne_l_appel(self, gitlab):
        """La portée vient du registre, jamais de la phrase tapée."""
        gitlab_api.tickets(source(), "glpat-x")
        assert "equipe%2Foutil" in gitlab.premier.full_url

    def test_le_jeton_voyage_en_entete_pas_dans_l_adresse(self, gitlab):
        gitlab_api.tickets(source(), "glpat-secret")
        assert gitlab.premier.get_header("Private-token") == "glpat-secret"
        assert "glpat-secret" not in gitlab.premier.full_url

    def test_seuls_les_ouverts_sont_demandes_par_defaut(self, gitlab):
        gitlab_api.tickets(source(), "glpat-x")
        assert "state=opened" in gitlab.premier.full_url

    def test_une_recherche_est_transmise(self, gitlab):
        gitlab_api.tickets(source(), "glpat-x", cherche="envoi")
        assert "search=envoi" in gitlab.premier.full_url

    def test_la_lecture_ne_demande_aucun_droit_d_ecriture(self, gitlab):
        assert gitlab_api.tickets(source(Right.LECTURE), "glpat-x") == []

    def test_les_demandes_de_fusion_se_lisent_aussi(self, gitlab):
        gitlab.charge = [UN_TICKET]
        trouvees = gitlab_api.join_requests(source(), "glpat-x")
        assert "merge_requests" in gitlab.premier.full_url
        assert trouvees[0].number == 42


class TestEcriture:
    def test_une_source_en_lecture_seule_n_appelle_meme_pas(self, muet):
        with pytest.raises(gitlab_api.GitLabRefused, match="lecture seule"):
            gitlab_api.creer_un_ticket(source(), "glpat-x", "Faire la chose")

    def test_commenter_est_une_ecriture(self, muet):
        """Un commentaire notifie des gens et reste attaché à leur travail."""
        with pytest.raises(gitlab_api.GitLabRefused, match="lecture seule"):
            gitlab_api.comment(source(), "glpat-x", 42, "vu")

    def test_un_titre_vide_est_refuse(self, muet):
        with pytest.raises(gitlab_api.GitLabRefused):
            gitlab_api.creer_un_ticket(source(Right.ECRITURE), "glpat-x", "  ")

    def test_un_commentaire_vide_est_refuse(self, muet):
        with pytest.raises(gitlab_api.GitLabRefused):
            gitlab_api.comment(source(Right.ECRITURE), "glpat-x", 42, "   ")

    def test_le_ticket_cree_est_rendu_avec_son_adresse(self, gitlab):
        """Une écriture dont on ne montre pas le résultat n'est pas vérifiable."""
        gitlab.charge = UN_TICKET
        cree = gitlab_api.creer_un_ticket(
            source(Right.ECRITURE), "glpat-x", "Corriger l'envoi"
        )
        assert cree.number == 42
        assert cree.adresse.endswith("/issues/42")
        assert gitlab.premier.method == "POST"

    def test_le_corps_porte_le_titre_donne(self, gitlab):
        gitlab.charge = UN_TICKET
        gitlab_api.creer_un_ticket(source(Right.ECRITURE), "glpat-x", "Un titre")
        assert json.loads(gitlab.premier.data)["title"] == "Un titre"

    def test_un_commentaire_rend_l_adresse_du_ticket(self, gitlab):
        gitlab.charge = {"id": 7}
        rendered = gitlab_api.comment(source(Right.ECRITURE), "glpat-x", 42, "vu")
        assert rendered.endswith("/equipe/outil/-/issues/42")
        assert gitlab.premier.method == "POST"


class TestQuandCaRateOnLeDit:
    def test_un_jeton_refuse_dit_la_portee_a_verifier(self, monkeypatch):
        echouer(monkeypatch, 401)
        with pytest.raises(gitlab_api.GitLabRefused, match="read_api"):
            gitlab_api.tickets(source(), "glpat-perime")

    def test_un_projet_introuvable_dit_qu_un_projet_prive_fait_pareil(self, monkeypatch):
        echouer(monkeypatch, 404)
        with pytest.raises(gitlab_api.GitLabRefused, match="privé"):
            gitlab_api.tickets(source(), "glpat-x")

    def test_un_serveur_injoignable_est_dit_sans_faire_tomber(self, monkeypatch):
        def tomber(*_args, **_options):
            raise urllib.error.URLError("nom introuvable")

        monkeypatch.setattr(gitlab_api.urllib.request, "urlopen", tomber)
        with pytest.raises(gitlab_api.GitLabRefused, match="injoignable"):
            gitlab_api.tickets(source(), "glpat-x")

    def test_une_reponse_inattendue_est_dite(self, gitlab):
        gitlab.charge = {"pas": "une liste"}
        with pytest.raises(gitlab_api.GitLabRefused):
            gitlab_api.tickets(source(), "glpat-x")
