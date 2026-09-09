"""Une mise à jour ne doit jamais emporter le travail de quelqu'un.

Greffier se met à jour en **remplaçant** son paquet : sur macOS,
`/Applications/Greffier.app` est reconstruit et écrasé, interpréteur, paquets et
code compris. Tout ce qui vivrait dedans disparaîtrait à cette occasion — les
réunions transcrites, les comptes rendus, la banque de voix, les conversations,
le contexte appris. Ces tests vérifient que rien de tout cela n'en dépend.

Ils ne lancent aucune application : ils lisent où les chemins pointent, ce qui
est précisément la question.
"""

from pathlib import Path

from greffier.adaptateurs.configuration import Config

#: Les endroits qu'une mise à jour remplace. Un chemin de données qui tomberait
#: là-dedans serait perdu à la première reconstruction.
REMPLACES = ("/Applications/", "site-packages", "/Contents/")


def tous_les_chemins(config: Config) -> dict[str, Path]:
    chemins = config.chemins
    return {
        "donnees": chemins.donnees,
        "modeles": chemins.modeles,
        "enregistrements": chemins.enregistrements,
        "transcriptions": chemins.transcriptions,
        "comptes_rendus": chemins.comptes_rendus,
        "banque_de_voix": chemins.banque_de_voix,
        "direct": chemins.direct,
        "propositions": chemins.propositions,
        "questions": chemins.questions,
        "conversations": chemins.conversations,
        "contexte": chemins.contexte,
    }


class TestRienNeVitDansLePaquet:
    def test_aucun_chemin_de_donnees_ne_tombe_dans_ce_qu_une_maj_remplace(self):
        fautifs = {
            nom: chemin
            for nom, chemin in tous_les_chemins(Config()).items()
            if any(morceau in str(chemin) for morceau in REMPLACES)
        }
        assert not fautifs, f"perdu à la prochaine mise à jour : {fautifs}"

    def test_les_donnees_ne_dependent_pas_du_dossier_de_travail(self):
        """Lancer depuis un autre dossier ne doit pas changer où l'on écrit.

        L'application est lancée par le système, sans dossier de travail
        prévisible : un chemin relatif désignerait un endroit différent à chaque
        démarrage, et les réunions de la veille deviendraient introuvables.
        """
        for nom, chemin in tous_les_chemins(Config()).items():
            assert chemin.is_absolute(), f"{nom} est relatif : {chemin}"

    def test_tout_est_rassemble_sous_un_seul_dossier_de_donnees(self):
        """Ce qui permet de sauvegarder, et de dire ce qu'une purge emporte."""
        config = Config()
        racine = config.chemins.donnees
        for nom, chemin in tous_les_chemins(config).items():
            if nom in {"donnees", "contexte"}:
                continue
            assert racine in chemin.parents or chemin == racine, f"{nom} hors de {racine}"


class TestUnAncienFichierResteLisible:
    """Une mise à jour ne doit pas rendre illisible ce qui était déjà écrit."""

    def test_le_format_du_fichier_maitre_n_a_qu_un_numero(self):
        """Deux définitions du format finiraient par se contredire."""
        from greffier.adaptateurs import depot_fichiers

        assert isinstance(depot_fichiers.FORMAT, int)
        assert depot_fichiers.FORMAT >= 2, "le format a évolué : la lecture doit suivre"

    def test_une_reunion_sans_les_champs_recents_se_lit(self, tmp_path):
        """Le cas d'une réunion écrite avant la mise à jour."""
        import json
        from datetime import UTC, datetime

        from greffier.adaptateurs.depot_fichiers import DepotFichiers

        minimal = {
            "format": 1,
            "identifiant": "2026-08-01_09h00_ancienne",
            "audio": "/tmp/ancienne.wav",
            "traitee_le": datetime.now(UTC).isoformat(),
            "duree": 60.0,
            "repliques": [{"debut": 0.0, "fin": 5.0, "texte": "Bonjour."}],
            "tours": [{"debut": 0.0, "fin": 5.0, "voix": "1"}],
        }
        chemin = tmp_path / "2026-08-01_09h00_ancienne.json"
        chemin.write_text(json.dumps(minimal), encoding="utf-8")
        relue = DepotFichiers(tmp_path).lire("2026-08-01_09h00_ancienne")
        assert relue.repliques[0].texte == "Bonjour."
        assert relue.sujet == ""
        assert relue.commencee_le is None
