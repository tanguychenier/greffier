"""Oublier une réunion : dire ce qui part, puis l'effacer."""

from pathlib import Path

from greffier.application.tidy import Places, forget, pieces_de, readable


def locations(root: Path) -> Places:
    where_in = Places(
        meetings=root / "reunions",
        recordings=root / "enregistrements",
        transcripts=root / "transcriptions",
        minutes_folder=root / "comptes-rendus",
        live=root / "direct",
        propositions=root / "propositions",
    )
    for folder in (where_in.meetings, where_in.recordings, where_in.transcripts,
                    where_in.minutes_folder, where_in.live, where_in.propositions):
        folder.mkdir(parents=True, exist_ok=True)
    return where_in


def lay_out_a_meeting(where_in: Places, identifier: str = "2026-09-09_10h05_reunion") -> None:
    (where_in.recordings / f"{identifier}.wav").write_bytes(b"x" * 5000)
    (where_in.meetings / f"{identifier}.json").write_text("{}", encoding="utf-8")
    (where_in.transcripts / f"{identifier}.txt").write_text("bonjour", encoding="utf-8")
    (where_in.minutes_folder / f"{identifier}.md").write_text("# cr", encoding="utf-8")
    (where_in.live / f"{identifier}.jsonl").write_text("{}", encoding="utf-8")
    (where_in.propositions / f"{identifier}.jsonl").write_text("{}", encoding="utf-8")


class TestWhatWillGo:
    """Une confirmation qui ne dit pas ce qu'elle efface ne vaut rien.

    Supprimer le seul fichier maître laissait 158 Mo d'audio orphelins et un
    compte rendu que plus rien ne référençait.
    """

    def test_every_piece_is_found(self, tmp_path):
        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in)
        what = {p.what for p in pieces_de(where_in, "2026-09-09_10h05_reunion")}
        assert what == {
            "enregistrement audio", "réunion transcrite", "transcription lisible",
            "compte rendu", "fil du direct", "propositions de noms",
        }

    def test_the_audio_comes_first_because_it_weighs(self, tmp_path):
        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in)
        assert pieces_de(where_in, "2026-09-09_10h05_reunion")[0].what == "enregistrement audio"

    def test_an_unknown_meeting_returns_nothing(self, tmp_path):
        assert pieces_de(locations(tmp_path), "jamais-vue") == []

    def test_a_compressed_audio_is_recognised(self, tmp_path):
        """« greffier archiver » remplace le WAV par un Opus : il compte aussi."""
        where_in = locations(tmp_path)
        (where_in.recordings / "2026-09-09_x.opus").write_bytes(b"x" * 10)
        assert [p.what for p in pieces_de(where_in, "2026-09-09_x")] == ["enregistrement audio"]


class TestForgettingAMeeting:
    def test_everything_is_deleted(self, tmp_path):
        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in)
        effacees = forget(where_in, "2026-09-09_10h05_reunion")
        assert len(effacees) == 6
        assert pieces_de(where_in, "2026-09-09_10h05_reunion") == []

    def test_the_other_meetings_are_untouched(self, tmp_path):
        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-09-09_10h05_reunion")
        lay_out_a_meeting(where_in, "2026-09-02_17h37_reunion")
        forget(where_in, "2026-09-09_10h05_reunion")
        assert len(pieces_de(where_in, "2026-09-02_17h37_reunion")) == 6

    def test_forgetting_twice_raises_nothing(self, tmp_path):
        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in)
        forget(where_in, "2026-09-09_10h05_reunion")
        assert forget(where_in, "2026-09-09_10h05_reunion") == []


class TestAWeightAPersonCanRead:
    def test_the_orders_of_magnitude(self):
        assert readable(512) == "512 o"
        assert readable(2048) == "2 Ko"
        assert readable(158137446) == "151 Mo"
        assert readable(3 * 1024**3) == "3.0 Go"


class TestTidyingByTheRetentionRule:
    """Constater d'abord : effacer un enregistrement ne se rattrape pas."""

    def the_usual_rule(self):
        from greffier.domain.retention import Rule

        return Rule(compresser_apres=7, effacer_apres=0)

    def test_looking_touches_nothing(self, tmp_path):
        from greffier.application.tidy import tidy

        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-08-01_09h00_vieille")
        audio = where_in.recordings / "2026-08-01_09h00_vieille.wav"
        faits = tidy(where_in, self.the_usual_rule(),
                       [("2026-08-01_09h00_vieille", 40.0, True)],
                       compresser=lambda path: path)
        assert [f.geste for f in faits] == ["compresser"]
        assert audio.exists(), "rien ne doit bouger sans --faire"

    def test_applying_it_compresses(self, tmp_path):
        from greffier.application.tidy import tidy

        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-08-01_09h00_vieille")
        compresses = []

        def compresser(path):
            compresses.append(path)
            produit = path.with_suffix(".opus")
            produit.write_bytes(b"x" * 100)
            path.unlink()
            return produit

        faits = tidy(where_in, self.the_usual_rule(),
                       [("2026-08-01_09h00_vieille", 40.0, True)],
                       compresser=compresser, for_real=True)
        assert compresses, "la compression doit être appelée"
        assert faits[0].gagne > 0

    def test_a_recent_meeting_is_left_alone(self, tmp_path):
        from greffier.application.tidy import tidy

        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-09-09_10h05_reunion")
        assert tidy(where_in, self.the_usual_rule(),
                      [("2026-09-09_10h05_reunion", 1.0, True)],
                      compresser=lambda c: c) == []

    def test_a_meeting_not_yet_transcribed_is_untouchable(self, tmp_path):
        """Son audio est tout ce qui existe d'elle."""
        from greffier.application.tidy import tidy

        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-08-01_09h00_jamais-traitee")
        assert tidy(where_in, self.the_usual_rule(),
                      [("2026-08-01_09h00_jamais-traitee", 365.0, False)],
                      compresser=lambda c: c) == []

    def test_a_compression_that_fails_is_reported(self, tmp_path):
        """Un ffmpeg absent ne doit pas interrompre le rangement des autres."""
        from greffier.application.tidy import tidy

        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-08-01_09h00_vieille")

        def tomber(_path):
            raise OSError("ffmpeg introuvable")

        faits = tidy(where_in, self.the_usual_rule(),
                       [("2026-08-01_09h00_vieille", 40.0, True)],
                       compresser=tomber, for_real=True)
        assert faits[0].trouble
        assert (where_in.recordings / "2026-08-01_09h00_vieille.wav").exists()

    def test_deleting_frees_all_the_audio(self, tmp_path):
        from greffier.application.tidy import tidy
        from greffier.domain.retention import Rule

        where_in = locations(tmp_path)
        lay_out_a_meeting(where_in, "2026-01-01_09h00_ancienne")
        audio = where_in.recordings / "2026-01-01_09h00_ancienne.wav"
        faits = tidy(where_in, Rule(compresser_apres=7, effacer_apres=90),
                       [("2026-01-01_09h00_ancienne", 200.0, True)],
                       compresser=lambda c: c, for_real=True)
        assert faits[0].geste == "effacer"
        assert not audio.exists()
        assert (where_in.transcripts / "2026-01-01_09h00_ancienne.txt").exists(), (
            "la transcription porte le travail : elle reste"
        )


class TestEverythingThatBelongsToTheMeeting:
    """Effacer une réunion doit tout prendre : sinon il reste des données.

    Les questions posées, la conversation tenue et les documents fournis
    vivaient hors de l'énumération : « effacer » laissait derrière lui ce que
    la réunion avait produit de plus bavard.
    """

    def place(self, tmp_path, identifier="reunion-1"):
        from greffier.application.tidy import Places

        for name in ("enregistrements", "reunions", "transcriptions",
                    "comptes-rendus", "direct", "propositions", "questions",
                    "conversations", "pieces"):
            (tmp_path / name).mkdir()
        (tmp_path / "questions" / f"{identifier}.jsonl").write_text("{}\n")
        (tmp_path / "conversations" / f"{identifier}.jsonl").write_text("{}\n")
        (tmp_path / "pieces" / identifier).mkdir()
        (tmp_path / "pieces" / identifier / "ordre-du-jour.txt").write_text("x")
        return Places(
            meetings=tmp_path / "reunions",
            recordings=tmp_path / "enregistrements",
            transcripts=tmp_path / "transcriptions",
            minutes_folder=tmp_path / "comptes-rendus",
            live=tmp_path / "direct",
            propositions=tmp_path / "propositions",
            questions=tmp_path / "questions",
            conversations=tmp_path / "conversations",
            pieces=tmp_path / "pieces",
        )

    def test_the_questions_and_the_conversation_are_counted(self, tmp_path):
        from greffier.application.tidy import pieces_de

        what = {p.what for p in pieces_de(self.place(tmp_path), "reunion-1")}
        assert "questions posées" in what
        assert "conversation avec l'assistant" in what

    def test_the_documents_handed_in_are_counted(self, tmp_path):
        from greffier.application.tidy import pieces_de

        found = pieces_de(self.place(tmp_path), "reunion-1")
        assert any("document fourni" in p.what for p in found)

    def test_forgetting_removes_the_documents_folder_too(self, tmp_path):
        """Un dossier vide laisse croire qu'il reste quelque chose."""
        from greffier.application.tidy import forget

        where_in = self.place(tmp_path)
        forget(where_in, "reunion-1")
        assert not (tmp_path / "pieces" / "reunion-1").exists()
        assert not (tmp_path / "questions" / "reunion-1.jsonl").exists()

    def test_the_optional_places_stay_optional(self, tmp_path):
        """Les appels existants construisent six champs, pas neuf."""
        from greffier.application.tidy import Places, pieces_de

        where_in = Places(
            meetings=tmp_path, recordings=tmp_path, transcripts=tmp_path,
            minutes_folder=tmp_path, live=tmp_path, propositions=tmp_path,
        )
        assert pieces_de(where_in, "reunion-1") == []
