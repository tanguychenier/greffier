"""Lire et écrire sur un Jira inscrit, et refuser le reste."""

import base64
import json
import urllib.error
from io import BytesIO

import pytest

from greffier.adapters import jira_api
from greffier.domain.sources import Kind, Right, Source

SECRET = "moi@exemple.fr:jeton-atlassian"


def source(droit: Right = Right.LECTURE) -> Source:
    return Source(
        name="suivi", kind=Kind.JIRA, adresse="https://exemple.atlassian.net",
        projet="PROJ", droit=droit, token="trousseau:greffier-jira",
    )


class Reponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FauxJira:
    def __init__(self) -> None:
        self.appels: list = []
        self.charge: object = {"issues": []}

    def __call__(self, requete, timeout=None):
        self.appels.append(requete)
        return Reponse(json.dumps(self.charge).encode("utf-8"))

    @property
    def premier(self):
        return self.appels[0]


@pytest.fixture
def jira(monkeypatch) -> FauxJira:
    faux = FauxJira()
    monkeypatch.setattr(jira_api.urllib.request, "urlopen", faux)
    return faux


@pytest.fixture
def muet(monkeypatch):
    def jamais(*_args, **_options):
        raise AssertionError("aucun appel ne devait partir")

    monkeypatch.setattr(jira_api.urllib.request, "urlopen", jamais)


UNE_DEMANDE = {
    "key": "PROJ-12",
    "fields": {
        "summary": "Reprendre la recette",
        "status": {"name": "En cours"},
        "assignee": {"displayName": "Sophie"},
    },
}


class TestIdentifiants:
    def test_le_secret_porte_l_adresse_et_le_jeton(self, jira):
        """Basic demande les deux ; un seul secret est à déposer."""
        jira_api.requests(source(), SECRET)
        attendu = base64.b64encode(SECRET.encode()).decode()
        assert jira.premier.get_header("Authorization") == f"Basic {attendu}"

    def test_un_secret_sans_adresse_est_dit_clairement(self, muet):
        with pytest.raises(jira_api.JiraRefused, match="adresse@exemple.fr"):
            jira_api.requests(source(), "jeton-tout-seul")

    def test_l_adresse_du_compte_n_est_pas_dans_le_registre(self):
        """Elle identifie une personne : elle vit dans le secret, pas ici."""
        assert "@" not in source().token


class TestLecture:
    def test_les_demandes_sont_rendues_utilisables(self, jira):
        jira.charge = {"issues": [UNE_DEMANDE]}
        trouvees = jira_api.requests(source(), SECRET)
        assert trouvees[0].key == "PROJ-12"
        assert trouvees[0].state == "En cours"
        assert trouvees[0].assigne == "Sophie"

    def test_l_adresse_web_se_deduit_de_la_clef(self, jira):
        jira.charge = {"issues": [UNE_DEMANDE]}
        adresse = jira_api.requests(source(), SECRET)[0].adresse
        assert adresse == "https://exemple.atlassian.net/browse/PROJ-12"

    def test_une_demande_sans_assigne_ne_casse_pas(self, jira):
        jira.charge = {"issues": [{**UNE_DEMANDE, "fields": {"summary": "x"}}]}
        rendue = jira_api.requests(source(), SECRET)[0]
        assert rendue.assigne == "" and rendue.state == ""

    def test_la_ligne_montre_la_demande_d_un_coup(self, jira):
        jira.charge = {"issues": [UNE_DEMANDE]}
        dit = jira_api.requests(source(), SECRET)[0].say()
        assert "PROJ-12" in dit and "Sophie" in dit and "En cours" in dit

    def test_le_projet_du_registre_borne_la_requete(self, jira):
        jira_api.requests(source(), SECRET)
        assert "PROJ" in jira.premier.full_url

    def test_ce_qui_est_termine_est_ecarte_par_defaut(self, jira):
        jira_api.requests(source(), SECRET)
        assert "statusCategory" in jira.premier.full_url

    def test_tout_peut_etre_demande(self, jira):
        jira_api.requests(source(), SECRET, ouvertes=False)
        assert "statusCategory" not in jira.premier.full_url


class TestEcriture:
    def test_une_source_en_lecture_seule_n_appelle_meme_pas(self, muet):
        with pytest.raises(jira_api.JiraRefused, match="lecture seule"):
            jira_api.creer_une_demande(source(), SECRET, "Faire la chose")

    def test_un_titre_vide_est_refuse(self, muet):
        with pytest.raises(jira_api.JiraRefused):
            jira_api.creer_une_demande(source(Right.ECRITURE), SECRET, " ")

    def test_la_demande_creee_est_rendue_avec_son_adresse(self, jira):
        jira.charge = {"key": "PROJ-13"}
        creee = jira_api.creer_une_demande(
            source(Right.ECRITURE), SECRET, "Reprendre la recette"
        )
        assert creee.key == "PROJ-13"
        assert creee.adresse.endswith("/browse/PROJ-13")
        assert jira.premier.method == "POST"

    def test_le_corps_nomme_le_projet_inscrit(self, jira):
        jira.charge = {"key": "PROJ-13"}
        jira_api.creer_une_demande(source(Right.ECRITURE), SECRET, "x")
        envoye = json.loads(jira.premier.data)
        assert envoye["fields"]["project"]["key"] == "PROJ"

    def test_la_description_part_au_format_document(self, jira):
        """Du texte brut est refusé par l'API 3, et l'erreur ne le dit pas."""
        jira.charge = {"key": "PROJ-13"}
        jira_api.creer_une_demande(
            source(Right.ECRITURE), SECRET, "x", description="parce que"
        )
        decrit = json.loads(jira.premier.data)["fields"]["description"]
        assert decrit["type"] == "doc"
        assert decrit["content"][0]["content"][0]["text"] == "parce que"

    def test_sans_description_aucun_champ_n_est_envoye(self, jira):
        jira.charge = {"key": "PROJ-13"}
        jira_api.creer_une_demande(source(Right.ECRITURE), SECRET, "x")
        assert "description" not in json.loads(jira.premier.data)["fields"]


class TestQuandCaRateOnLeDit:
    def test_des_identifiants_refuses_disent_quoi_verifier(self, monkeypatch):
        def tomber(*_args, **_options):
            raise urllib.error.HTTPError(
                "https://x", 401, "non", {}, BytesIO(b"{}")  # type: ignore[arg-type]
            )

        monkeypatch.setattr(jira_api.urllib.request, "urlopen", tomber)
        with pytest.raises(jira_api.JiraRefused, match="jeton"):
            jira_api.requests(source(), SECRET)

    def test_un_serveur_injoignable_est_dit_sans_faire_tomber(self, monkeypatch):
        def tomber(*_args, **_options):
            raise urllib.error.URLError("nom introuvable")

        monkeypatch.setattr(jira_api.urllib.request, "urlopen", tomber)
        with pytest.raises(jira_api.JiraRefused, match="injoignable"):
            jira_api.requests(source(), SECRET)

    def test_une_reponse_inattendue_est_dite(self, jira):
        jira.charge = ["pas un objet"]
        with pytest.raises(jira_api.JiraRefused):
            jira_api.requests(source(), SECRET)
