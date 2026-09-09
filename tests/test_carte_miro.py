"""Écrire une carte sur Miro : ce qui est refusé avant tout appel."""

import pytest

from greffier.adaptateurs import carte_miro
from greffier.adaptateurs.carte_miro import INTERDITS, MiroRefuse, jeton


class TestTableauxInterdits:
    """Un tableau documentant un circuit de signature n'appartient pas à l'outil.

    Écrire dessus a été explicitement défendu, et la question a déjà été posée
    une fois par son auteur. C'est donc dans le code, pas dans une consigne.
    """

    def test_la_liste_n_est_pas_vide(self):
        assert INTERDITS

    def test_publier_sur_un_interdit_echoue_avant_tout_appel(self, monkeypatch):
        def jamais(*_args, **_options):
            raise AssertionError("aucun appel ne doit partir")

        monkeypatch.setattr(carte_miro, "_appeler", jamais)
        with pytest.raises(MiroRefuse, match="interdits"):
            carte_miro.textes_presents(next(iter(INTERDITS)))


class TestJeton:
    def test_l_environnement_est_lu_d_abord(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "abc")
        assert jeton() == "abc"

    def test_un_fichier_peut_le_porter(self, monkeypatch, tmp_path):
        fichier = tmp_path / "jeton.txt"
        fichier.write_text("depuis-le-fichier\n", encoding="utf-8")
        monkeypatch.delenv("GREFFIER_MIRO_JETON", raising=False)
        monkeypatch.setenv("GREFFIER_MIRO_JETON_FICHIER", str(fichier))
        assert jeton() == "depuis-le-fichier"

    def test_sans_jeton_le_message_dit_quoi_faire(self, monkeypatch):
        monkeypatch.delenv("GREFFIER_MIRO_JETON", raising=False)
        monkeypatch.delenv("GREFFIER_MIRO_JETON_FICHIER", raising=False)
        with pytest.raises(MiroRefuse, match="GREFFIER_MIRO_JETON"):
            jeton()

    def test_aucun_chemin_n_est_ecrit_en_dur(self):
        """Un outil public ne va pas chercher dans le dossier d'un projet."""
        from pathlib import Path

        source = Path(carte_miro.__file__).read_text(encoding="utf-8")
        assert "cidr" not in source.lower()
        assert "/var/miro" not in source


class TestPublicationSansReseau:
    def marquer(self, monkeypatch, presents=(), poses=None):
        """Remplace l'API par une doublure qui note ce qu'on lui demande."""
        appels = []

        def faux(chemin, methode="GET", corps=None):
            appels.append((methode, chemin, corps))
            if "/items" in chemin:
                return {"data": [
                    {"data": {"content": f"<p>{texte}</p>"}} for texte in presents
                ]}
            return {"id": f"objet-{len(appels)}"}

        monkeypatch.setattr(carte_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return appels

    def test_seuls_les_noeuds_manquants_sont_poses(self, monkeypatch):
        from greffier.domaine.carte import Apport, Carte, fusionner

        carte = Carte("Oasis")
        fusionner(carte, [Apport("Déjà là"), Apport("Nouveau")])
        self.marquer(monkeypatch, presents=("Oasis", "Déjà là"))
        ecrit = carte_miro.publier(carte, "uXjVtest=")
        assert ecrit.poses == ("Nouveau",)
        assert set(ecrit.deja) == {"Oasis", "Déjà là"}

    def test_rien_n_est_supprime_ni_modifie(self, monkeypatch):
        """Ce que quelqu'un a posé reste tel quel."""
        from greffier.domaine.carte import Apport, Carte, fusionner

        carte = Carte("Oasis")
        fusionner(carte, [Apport("Un point")])
        appels = self.marquer(monkeypatch)
        carte_miro.publier(carte, "uXjVtest=")
        methodes = {methode for methode, _, _ in appels}
        assert methodes <= {"GET", "POST"}, "ni DELETE ni PATCH"

    def test_l_etat_se_lit_a_la_couleur(self, monkeypatch):
        from greffier.domaine.carte import Apport, Carte, Etat, Genre, fusionner

        carte = Carte("Oasis")
        # Une piste : seuls une piste et une action peuvent être actées.
        fusionner(carte, [Apport("Décidé", genre=Genre.PISTE, etat=Etat.ACTE)])
        appels = self.marquer(monkeypatch)
        carte_miro.publier(carte, "uXjVtest=")
        couleurs = [
            corps["style"]["fillColor"]
            for methode, chemin, corps in appels
            if methode == "POST" and "sticky_notes" in chemin and corps
        ]
        assert carte_miro.COULEURS[Etat.ACTE] in couleurs

    def test_le_texte_est_echappe(self, monkeypatch):
        """Un « < » dans un libellé ne doit pas casser le contenu HTML."""
        from greffier.domaine.carte import Apport, Carte, fusionner

        carte = Carte("Oasis")
        fusionner(carte, [Apport("a < b & c")])
        appels = self.marquer(monkeypatch)
        carte_miro.publier(carte, "uXjVtest=")
        contenus = [
            corps["data"]["content"]
            for methode, chemin, corps in appels
            if methode == "POST" and "sticky_notes" in chemin and corps
        ]
        assert any("&lt;" in contenu and "&amp;" in contenu for contenu in contenus)
