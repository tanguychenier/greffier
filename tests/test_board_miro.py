"""Écrire une carte sur Miro : ce qui est refusé avant tout appel."""

import pytest

from greffier.adapters import board_miro
from greffier.adapters.board_miro import INTERDITS, MiroRefused, token


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

        monkeypatch.setattr(board_miro, "_appeler", jamais)
        with pytest.raises(MiroRefused, match="interdits"):
            board_miro.textes_presents(next(iter(INTERDITS)))


class TestJeton:
    def test_l_environnement_est_lu_d_abord(self, monkeypatch):
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "abc")
        assert token() == "abc"

    def test_un_fichier_peut_le_porter(self, monkeypatch, tmp_path):
        file = tmp_path / "jeton.txt"
        file.write_text("depuis-le-fichier\n", encoding="utf-8")
        monkeypatch.delenv("GREFFIER_MIRO_JETON", raising=False)
        monkeypatch.setenv("GREFFIER_MIRO_JETON_FICHIER", str(file))
        assert token() == "depuis-le-fichier"

    def test_sans_jeton_le_message_dit_quoi_faire(self, monkeypatch):
        monkeypatch.delenv("GREFFIER_MIRO_JETON", raising=False)
        monkeypatch.delenv("GREFFIER_MIRO_JETON_FICHIER", raising=False)
        with pytest.raises(MiroRefused, match="GREFFIER_MIRO_JETON"):
            token()

    def test_aucun_chemin_n_est_ecrit_en_dur(self):
        """Un outil public ne va pas chercher dans le dossier d'un projet."""
        from pathlib import Path

        source = Path(board_miro.__file__).read_text(encoding="utf-8")
        assert "cidr" not in source.lower()
        assert "/var/miro" not in source


class TestPublicationSansReseau:
    def mark(self, monkeypatch, present_line=(), poses=None):
        """Remplace l'API par une doublure qui note ce qu'on lui demande."""
        appels = []

        def faux(path, methode="GET", corps=None):
            appels.append((methode, path, corps))
            if "/items" in path:
                return {"data": [
                    {"data": {"content": f"<p>{text}</p>"}} for text in present_line
                ]}
            return {"id": f"objet-{len(appels)}"}

        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return appels

    def test_seuls_les_noeuds_manquants_sont_poses(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Déjà là"), Contribution("Nouveau")])
        self.mark(monkeypatch, present_line=("Oasis", "Déjà là"))
        ecrit = board_miro.publish(board, "uXjVtest=")
        assert ecrit.poses == ("Nouveau",)
        assert set(ecrit.deja) == {"Oasis", "Déjà là"}

    def test_rien_n_est_supprime_ni_modifie(self, monkeypatch):
        """Ce que quelqu'un a posé reste tel quel."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Un point")])
        appels = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        methodes = {methode for methode, _, _ in appels}
        assert methodes <= {"GET", "POST"}, "ni DELETE ni PATCH"

    def test_l_etat_se_lit_a_la_couleur(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, Kind, Standing, join

        board = Board("Oasis")
        # Une piste : seuls une piste et une action peuvent être actées.
        join(board, [Contribution("Décidé", kind=Kind.PISTE, state=Standing.ACTE)])
        appels = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        colours = [
            corps["style"]["fillColor"]
            for methode, path, corps in appels
            if methode == "POST" and "sticky_notes" in path and corps
        ]
        assert board_miro.COLOURS[Standing.ACTE] in colours

    def test_le_texte_est_echappe(self, monkeypatch):
        """Un « < » dans un libellé ne doit pas casser le contenu HTML."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("a < b & c")])
        appels = self.mark(monkeypatch)
        board_miro.publish(board, "uXjVtest=")
        contenus = [
            corps["data"]["content"]
            for methode, path, corps in appels
            if methode == "POST" and "sticky_notes" in path and corps
        ]
        assert any("&lt;" in content and "&amp;" in content for content in contenus)


class TestConnecteurs:
    """Une carte sans un seul trait a été publiée sans que rien ne le dise."""

    def mark(self, monkeypatch):
        appels = []

        def faux(path, methode="GET", corps=None):
            appels.append((methode, path, corps))
            if "/items" in path:
                return {"data": []}
            return {"id": "3458764683144805305"}

        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        return appels

    def test_les_identifiants_partent_en_nombres(self):
        """L'API les refuse en chaînes : « expected of type [Number] »."""
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("Un point")])
        appels = []

        def faux(path, methode="GET", corps=None):
            appels.append((methode, path, corps))
            if "/items" in path:
                return {"data": []}
            return {"id": "3458764683144805305"}

        import pytest as _pytest
        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        try:
            board_miro.publish(board, "uXjVtest=")
        finally:
            monkeypatch.undo()
        liens = [corps for methode, path, corps in appels
                 if "connectors" in path and corps]
        assert liens, "un lien doit être tracé"
        assert isinstance(liens[0]["startItem"]["id"], int)

    def test_les_liens_traces_sont_comptes(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("A"), Contribution("B")])
        self.mark(monkeypatch)
        ecrit = board_miro.publish(board, "uXjVtest=")
        assert ecrit.liens == 2
        assert ecrit.liens_manques == 0

    def test_les_liens_echoues_sont_comptes_et_non_avales(self, monkeypatch):
        from greffier.domain.board import Board, Contribution, join

        board = Board("Oasis")
        join(board, [Contribution("A")])

        def faux(path, methode="GET", corps=None):
            if "/items" in path:
                return {"data": []}
            if "connectors" in path:
                raise board_miro.MiroRefused("refusé")
            return {"id": "3458764683144805305"}

        monkeypatch.setattr(board_miro, "_appeler", faux)
        monkeypatch.setenv("GREFFIER_MIRO_JETON", "essai")
        ecrit = board_miro.publish(board, "uXjVtest=")
        assert ecrit.liens == 0
        assert ecrit.liens_manques == 1, "l'échec doit se compter"


class TestLaRacine:
    def test_le_sujet_ne_porte_pas_d_etat(self):
        """« Oasis — en discussion » ferait dire que le sujet est en débat."""
        from greffier.domain.board import Board

        board = Board("Oasis")
        assert board.racine is not None
        html = board_miro._as_html(board.racine, "")
        assert "en discussion" not in html

    def test_le_sujet_a_sa_propre_couleur(self):
        from greffier.domain.board import Kind

        assert Kind.SUBJECT in __import__(
            "greffier.domain.board", fromlist=["SANS_ETAT"]
        ).SANS_ETAT
