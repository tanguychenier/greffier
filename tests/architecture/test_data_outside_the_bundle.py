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

from greffier.adapters.configuration import Config

#: Les endroits qu'une mise à jour remplace. Un chemin de données qui tomberait
#: là-dedans serait perdu à la première reconstruction.
REMPLACES = ("/Applications/", "site-packages", "/Contents/")


def tous_les_chemins(config: Config) -> dict[str, Path]:
    paths = config.paths
    return {
        "donnees": paths.data,
        "modeles": paths.models,
        "enregistrements": paths.recordings,
        "transcriptions": paths.transcripts,
        "comptes_rendus": paths.minutes_folder,
        "banque_de_voix": paths.voice_bank,
        "direct": paths.live,
        "propositions": paths.propositions,
        "questions": paths.questions,
        "conversations": paths.conversations,
        "contexte": paths.context,
    }


class TestRienNeVitDansLePaquet:
    def test_aucun_chemin_de_donnees_ne_tombe_dans_ce_qu_une_maj_remplace(self):
        fautifs = {
            name: path
            for name, path in tous_les_chemins(Config()).items()
            if any(morceau in str(path) for morceau in REMPLACES)
        }
        assert not fautifs, f"perdu à la prochaine mise à jour : {fautifs}"

    def test_les_donnees_ne_dependent_pas_du_dossier_de_travail(self):
        """Lancer depuis un autre dossier ne doit pas changer où l'on écrit.

        L'application est lancée par le système, sans dossier de travail
        prévisible : un chemin relatif désignerait un endroit différent à chaque
        démarrage, et les réunions de la veille deviendraient introuvables.
        """
        for name, path in tous_les_chemins(Config()).items():
            assert path.is_absolute(), f"{name} est relatif : {path}"

    def test_tout_est_rassemble_sous_un_seul_dossier_de_donnees(self):
        """Ce qui permet de sauvegarder, et de dire ce qu'une purge emporte."""
        config = Config()
        racine = config.paths.data
        for name, path in tous_les_chemins(config).items():
            if name in {"donnees", "contexte"}:
                continue
            assert racine in path.parents or path == racine, f"{name} hors de {racine}"


class TestUnAncienFichierResteLisible:
    """Une mise à jour ne doit pas rendre illisible ce qui était déjà écrit."""

    def test_le_format_du_fichier_maitre_n_a_qu_un_numero(self):
        """Deux définitions du format finiraient par se contredire."""
        from greffier.adapters import store_files

        assert isinstance(store_files.FORMAT, int)
        assert store_files.FORMAT >= 2, "le format a évolué : la lecture doit suivre"

    def test_une_reunion_sans_les_champs_recents_se_lit(self, tmp_path):
        """Le cas d'une réunion écrite avant la mise à jour."""
        import json
        from datetime import UTC, datetime

        from greffier.adapters.store_files import FileStore

        minimal = {
            "format": 1,
            "identifiant": "2026-08-01_09h00_ancienne",
            "audio": "/tmp/ancienne.wav",
            "traitee_le": datetime.now(UTC).isoformat(),
            "duree": 60.0,
            "repliques": [{"debut": 0.0, "fin": 5.0, "texte": "Bonjour."}],
            "tours": [{"debut": 0.0, "fin": 5.0, "voix": "1"}],
        }
        path = tmp_path / "2026-08-01_09h00_ancienne.json"
        path.write_text(json.dumps(minimal), encoding="utf-8")
        relue = FileStore(tmp_path).read("2026-08-01_09h00_ancienne")
        assert relue.utterances[0].text == "Bonjour."
        assert relue.subject == ""
        assert relue.commencee_le is None
