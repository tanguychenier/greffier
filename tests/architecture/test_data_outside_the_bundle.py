"""An update must never carry away somebody's work.

Greffier updates itself by **replacing** its bundle: on macOS,
`/Applications/Greffier.app` is rebuilt and overwritten, interpreter, packages
and code included. Anything living inside it would disappear on that occasion:
the transcribed meetings, the minutes, the voice bank, the conversations, the
context learnt. These tests check that none of it depends on the bundle.

They launch no application: they read where the paths point, which is precisely
the question.
"""

from pathlib import Path

from greffier.adapters.configuration import Config

#: The places an update replaces. A data path falling in there would be lost on
#: the first rebuild.
REMPLACES = ("/Applications/", "site-packages", "/Contents/")


def every_path(config: Config) -> dict[str, Path]:
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


class TestNothingLivesInsideTheBundle:
    def test_no_data_path_falls_where_an_update_replaces_things(self):
        fautifs = {
            name: path
            for name, path in every_path(Config()).items()
            if any(morceau in str(path) for morceau in REMPLACES)
        }
        assert not fautifs, f"perdu à la prochaine mise à jour : {fautifs}"

    def test_the_data_does_not_depend_on_the_working_folder(self):
        """Launching from another folder must not change where things are written.

        The application is launched by the system, with no predictable working folder:
        a relative path would name a different place on every start, and yesterday's
        meetings would become impossible to find.
        """
        for name, path in every_path(Config()).items():
            assert path.is_absolute(), f"{name} est relatif : {path}"

    def test_everything_gathers_under_one_data_folder(self):
        """What makes a backup possible, and what a purge takes away sayable."""
        config = Config()
        root = config.paths.data
        for name, path in every_path(config).items():
            if name in {"donnees", "contexte"}:
                continue
            assert root in path.parents or path == root, f"{name} hors de {root}"


class TestAnOlderFileStaysReadable:
    """An update must not make unreadable what was already written."""

    def test_the_master_file_format_has_a_single_number(self):
        """Two definitions of the format would end up contradicting each other."""
        from greffier.adapters import store_files

        assert isinstance(store_files.FORMAT, int)
        assert store_files.FORMAT >= 2, "le format a évolué : la lecture doit suivre"

    def test_a_meeting_without_the_recent_fields_reads(self, tmp_path):
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
        assert relue.started_at is None
