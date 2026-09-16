"""Forgetting somebody, everywhere the tool wrote them down."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from greffier.application.erase_person import Everywhere, erase, inventory
from greffier.domain.erasure import UNNAMED


@pytest.fixture
def data(tmp_path: Path) -> Everywhere:
    """A machine that has held one meeting, with all its leftovers."""
    for folder in ("reunions", "comptes-rendus", "transcriptions", "direct",
                   "propositions", "questions", "conversations", "preparations"):
        (tmp_path / folder).mkdir()

    (tmp_path / "reunions" / "2026-09-10_reunion.json").write_text(json.dumps({
        "format": 2,
        "identifiant": "2026-09-10_reunion",
        "audio": "/data/enregistrements/2026-09-10_sophie.wav",
        "noms": {"v1": "Sophie", "v2": "Julien"},
        "propositions": {"v3": "Sophie"},
        "repliques": [
            {"debut": 0.0, "fin": 2.0, "texte": "Sophie prend la recette.",
             "voix": "v2"},
            {"debut": 2.0, "fin": 4.0, "texte": "D'accord.", "voix": "v1"},
        ],
        "fusions": [{"absorbee": "v4", "gardee": "v1", "tours": [],
                      "repliques": [], "nom": "Sophie", "proposition": None}],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "comptes-rendus" / "2026-09-10_reunion.md").write_text(
        "# Compte rendu\n\n- Sophie reprend la recette.\n- Julien relit.\n",
        encoding="utf-8",
    )
    (tmp_path / "transcriptions" / "2026-09-10_reunion.txt").write_text(
        "Sophie : je prends.\nJulien : d'accord.\n", encoding="utf-8",
    )
    (tmp_path / "direct" / "2026-09-10_reunion.jsonl").write_text(
        json.dumps({"voix": "v1", "nom": "Sophie", "texte": "je prends"},
                    ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "propositions" / "2026-09-10_reunion.jsonl").write_text(
        json.dumps({"voix": "v3", "prenom": "Sophie"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "questions" / "2026-09-10_reunion.jsonl").write_text(
        json.dumps({"question": "Sophie, c'est bien vous ?"},
                    ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "conversations" / "2026-09-10_reunion.jsonl").write_text(
        json.dumps({"qui": "moi", "dit": "demande à Sophie"},
                    ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "preparations" / "2026-09-20_point.json").write_text(
        json.dumps({"attendus": ["Sophie", "Julien"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "memoire.jsonl").write_text(
        json.dumps({"decision": "Sophie reprend la recette"},
                    ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "incidents.log").write_text(
        "2026-09-10 modeles : rien à voir\n", encoding="utf-8",
    )
    return Everywhere(
        meetings=tmp_path / "reunions",
        minutes_folder=tmp_path / "comptes-rendus",
        transcripts=tmp_path / "transcriptions",
        live=tmp_path / "direct",
        propositions=tmp_path / "propositions",
        questions=tmp_path / "questions",
        conversations=tmp_path / "conversations",
        preparations=tmp_path / "preparations",
        memory=tmp_path / "memoire.jsonl",
        troubles=tmp_path / "incidents.log",
    )


class TestSayingWhereSomebodyIsBeforeErasingThem:
    def test_every_kind_of_file_is_looked_at(self, data: Everywhere) -> None:
        what = {trace.what for trace in inventory(data, "Sophie")}
        assert what == {
            "réunion transcrite", "compte rendu", "transcription lisible",
            "fil du direct", "propositions de noms", "questions posées",
            "conversation avec l'assistant", "réunion préparée",
            "mémoire des réunions",
        }

    def test_a_file_that_never_names_them_is_not_listed(self, data: Everywhere) -> None:
        assert not [
            trace for trace in inventory(data, "Sophie")
            if trace.what == "journal des incidents"
        ]

    def test_the_heaviest_comes_first(self, data: Everywhere) -> None:
        traces = inventory(data, "Sophie")
        assert traces == sorted(traces, key=lambda t: (-t.occurrences, str(t.path)))
        assert traces[0].what == "réunion transcrite"

    def test_the_voiceprints_are_said_to_be_biometric(self, data: Everywhere) -> None:
        traces = inventory(data, "Sophie", voiceprints=3)
        biometrique = [trace for trace in traces if trace.biometric]
        assert [trace.occurrences for trace in biometrique] == [3]

    def test_looking_changes_nothing(self, data: Everywhere) -> None:
        avant = (data.minutes_folder / "2026-09-10_reunion.md").read_text()
        inventory(data, "Sophie")
        assert (data.minutes_folder / "2026-09-10_reunion.md").read_text() == avant


class TestErasingThem:
    def test_the_name_is_gone_from_the_minutes(self, data: Everywhere) -> None:
        erase(data, "Sophie")
        minutes_text = (data.minutes_folder / "2026-09-10_reunion.md").read_text()
        assert "Sophie" not in minutes_text
        assert UNNAMED in minutes_text
        assert "Julien relit." in minutes_text

    def test_the_decision_survives_the_person(self, data: Everywhere) -> None:
        # A meeting is not erased with somebody who attended it: what was
        # decided around that table belongs to everyone who was there.
        erase(data, "Sophie")
        assert "reprend la recette" in (
            data.minutes_folder / "2026-09-10_reunion.md"
        ).read_text()

    def test_the_master_file_is_still_a_master_file(self, data: Everywhere) -> None:
        erase(data, "Sophie")
        content = json.loads(
            (data.meetings / "2026-09-10_reunion.json").read_text()
        )
        assert content["noms"] == {"v1": UNNAMED, "v2": "Julien"}
        assert content["propositions"] == {"v3": UNNAMED}
        assert content["repliques"][0]["texte"] == f"{UNNAMED} prend la recette."
        assert content["fusions"][0]["nom"] == UNNAMED
        assert content["format"] == 2

    def test_the_recording_is_still_where_it_was(self, data: Everywhere) -> None:
        # « 2026-09-10_sophie.wav » redacted is a meeting pointing at a file
        # that does not exist, and the audio is the one piece nothing rebuilds.
        erase(data, "Sophie")
        content = json.loads(
            (data.meetings / "2026-09-10_reunion.json").read_text()
        )
        assert content["audio"].endswith("2026-09-10_sophie.wav")
        assert content["identifiant"] == "2026-09-10_reunion"

    def test_the_line_by_line_files_keep_one_object_per_line(
        self, data: Everywhere
    ) -> None:
        erase(data, "Sophie")
        for folder in (data.live, data.propositions, data.questions,
                        data.conversations):
            for path in folder.glob("*.jsonl"):
                for line in path.read_text().splitlines():
                    assert json.loads(line)
                    assert "Sophie" not in line

    def test_the_memory_carried_forward_forgets_too(self, data: Everywhere) -> None:
        erase(data, "Sophie")
        assert data.memory is not None
        assert "Sophie" not in data.memory.read_text()

    def test_a_meeting_yet_to_be_held_stops_expecting_them(
        self, data: Everywhere
    ) -> None:
        erase(data, "Sophie")
        assert data.preparations is not None
        expected = json.loads(
            (data.preparations / "2026-09-20_point.json").read_text()
        )["attendus"]
        assert expected == [UNNAMED, "Julien"]

    def test_a_file_that_does_not_name_them_is_not_rewritten(
        self, data: Everywhere
    ) -> None:
        assert data.troubles is not None
        before = data.troubles.stat().st_mtime_ns
        erase(data, "Sophie")
        assert data.troubles.stat().st_mtime_ns == before

    def test_it_says_what_it_did(self, data: Everywhere) -> None:
        done = erase(data, "Sophie")
        assert done.files == 9
        assert done.occurrences == 12
        assert {trace.what for trace in done.traces} == {
            "réunion transcrite", "compte rendu", "transcription lisible",
            "fil du direct", "propositions de noms", "questions posées",
            "conversation avec l'assistant", "réunion préparée",
            "mémoire des réunions",
        }

    def test_nothing_of_them_is_left_anywhere(self, data: Everywhere) -> None:
        erase(data, "Sophie")
        assert inventory(data, "Sophie") == []


class TestTheBankAndTheIndex:
    def test_both_are_asked_and_counted(self, data: Everywhere) -> None:
        asked: list[str] = []

        def bank(name: str) -> int:
            asked.append(f"banque:{name}")
            return 4

        def index(name: str) -> int:
            asked.append(f"index:{name}")
            return 2

        done = erase(data, "Sophie", forget_the_voiceprints=bank,
                      forget_in_the_index=index)
        assert asked == ["banque:Sophie", "index:Sophie"]
        assert done.voiceprints == 4
        assert done.index_entries == 2
        assert any(trace.biometric for trace in done.traces)

    def test_without_them_only_the_files_are_touched(self, data: Everywhere) -> None:
        done = erase(data, "Sophie")
        assert (done.voiceprints, done.index_entries) == (0, 0)
        assert not any(trace.biometric for trace in done.traces)


class TestAMachineWithNothingOnIt:
    def test_folders_that_do_not_exist_are_not_a_failure(self, tmp_path: Path) -> None:
        nulle_part = Everywhere(
            meetings=tmp_path / "reunions",
            minutes_folder=tmp_path / "comptes-rendus",
            transcripts=tmp_path / "transcriptions",
            live=tmp_path / "direct",
            propositions=tmp_path / "propositions",
        )
        assert inventory(nulle_part, "Sophie") == []
        assert erase(nulle_part, "Sophie").traces == []
