"""Oublier une réunion : dire ce qui part, puis l'effacer."""

from pathlib import Path

from greffier.application.ranger import Emplacements, lisible, oublier, pieces_de


def emplacements(racine: Path) -> Emplacements:
    ou = Emplacements(
        reunions=racine / "reunions",
        enregistrements=racine / "enregistrements",
        transcriptions=racine / "transcriptions",
        comptes_rendus=racine / "comptes-rendus",
        direct=racine / "direct",
        propositions=racine / "propositions",
    )
    for dossier in (ou.reunions, ou.enregistrements, ou.transcriptions,
                    ou.comptes_rendus, ou.direct, ou.propositions):
        dossier.mkdir(parents=True, exist_ok=True)
    return ou


def poser_une_reunion(ou: Emplacements, identifiant: str = "2026-09-09_10h05_reunion") -> None:
    (ou.enregistrements / f"{identifiant}.wav").write_bytes(b"x" * 5000)
    (ou.reunions / f"{identifiant}.json").write_text("{}", encoding="utf-8")
    (ou.transcriptions / f"{identifiant}.txt").write_text("bonjour", encoding="utf-8")
    (ou.comptes_rendus / f"{identifiant}.md").write_text("# cr", encoding="utf-8")
    (ou.direct / f"{identifiant}.jsonl").write_text("{}", encoding="utf-8")
    (ou.propositions / f"{identifiant}.jsonl").write_text("{}", encoding="utf-8")


class TestCeQuiVaPartir:
    """Une confirmation qui ne dit pas ce qu'elle efface ne vaut rien.

    Supprimer le seul fichier maître laissait 158 Mo d'audio orphelins et un
    compte rendu que plus rien ne référençait.
    """

    def test_toutes_les_pieces_sont_trouvees(self, tmp_path):
        ou = emplacements(tmp_path)
        poser_une_reunion(ou)
        quoi = {p.quoi for p in pieces_de(ou, "2026-09-09_10h05_reunion")}
        assert quoi == {
            "enregistrement audio", "réunion transcrite", "transcription lisible",
            "compte rendu", "fil du direct", "propositions de noms",
        }

    def test_l_audio_vient_en_tete_parce_qu_il_pese(self, tmp_path):
        ou = emplacements(tmp_path)
        poser_une_reunion(ou)
        assert pieces_de(ou, "2026-09-09_10h05_reunion")[0].quoi == "enregistrement audio"

    def test_une_reunion_inconnue_ne_rend_rien(self, tmp_path):
        assert pieces_de(emplacements(tmp_path), "jamais-vue") == []

    def test_un_audio_compresse_est_reconnu(self, tmp_path):
        """« greffier archiver » remplace le WAV par un Opus : il compte aussi."""
        ou = emplacements(tmp_path)
        (ou.enregistrements / "2026-09-09_x.opus").write_bytes(b"x" * 10)
        assert [p.quoi for p in pieces_de(ou, "2026-09-09_x")] == ["enregistrement audio"]


class TestOubli:
    def test_tout_est_efface(self, tmp_path):
        ou = emplacements(tmp_path)
        poser_une_reunion(ou)
        effacees = oublier(ou, "2026-09-09_10h05_reunion")
        assert len(effacees) == 6
        assert pieces_de(ou, "2026-09-09_10h05_reunion") == []

    def test_les_autres_reunions_ne_sont_pas_touchees(self, tmp_path):
        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-09-09_10h05_reunion")
        poser_une_reunion(ou, "2026-09-02_17h37_reunion")
        oublier(ou, "2026-09-09_10h05_reunion")
        assert len(pieces_de(ou, "2026-09-02_17h37_reunion")) == 6

    def test_oublier_deux_fois_ne_leve_rien(self, tmp_path):
        ou = emplacements(tmp_path)
        poser_une_reunion(ou)
        oublier(ou, "2026-09-09_10h05_reunion")
        assert oublier(ou, "2026-09-09_10h05_reunion") == []


class TestPoidsLisible:
    def test_les_ordres_de_grandeur(self):
        assert lisible(512) == "512 o"
        assert lisible(2048) == "2 Ko"
        assert lisible(158137446) == "151 Mo"
        assert lisible(3 * 1024**3) == "3.0 Go"


class TestRangementSelonLaRetention:
    """Constater d'abord : effacer un enregistrement ne se rattrape pas."""

    def regle_courante(self):
        from greffier.domaine.retention import Regle

        return Regle(compresser_apres=7, effacer_apres=0)

    def test_constater_ne_touche_a_rien(self, tmp_path):
        from greffier.application.ranger import ranger

        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-08-01_09h00_vieille")
        audio = ou.enregistrements / "2026-08-01_09h00_vieille.wav"
        faits = ranger(ou, self.regle_courante(),
                       [("2026-08-01_09h00_vieille", 40.0, True)],
                       compresser=lambda chemin: chemin)
        assert [f.geste for f in faits] == ["compresser"]
        assert audio.exists(), "rien ne doit bouger sans --faire"

    def test_appliquer_compresse(self, tmp_path):
        from greffier.application.ranger import ranger

        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-08-01_09h00_vieille")
        compresses = []

        def compresser(chemin):
            compresses.append(chemin)
            produit = chemin.with_suffix(".opus")
            produit.write_bytes(b"x" * 100)
            chemin.unlink()
            return produit

        faits = ranger(ou, self.regle_courante(),
                       [("2026-08-01_09h00_vieille", 40.0, True)],
                       compresser=compresser, pour_de_vrai=True)
        assert compresses, "la compression doit être appelée"
        assert faits[0].gagne > 0

    def test_une_reunion_recente_est_laissee(self, tmp_path):
        from greffier.application.ranger import ranger

        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-09-09_10h05_reunion")
        assert ranger(ou, self.regle_courante(),
                      [("2026-09-09_10h05_reunion", 1.0, True)],
                      compresser=lambda c: c) == []

    def test_une_reunion_non_transcrite_est_intouchable(self, tmp_path):
        """Son audio est tout ce qui existe d'elle."""
        from greffier.application.ranger import ranger

        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-08-01_09h00_jamais-traitee")
        assert ranger(ou, self.regle_courante(),
                      [("2026-08-01_09h00_jamais-traitee", 365.0, False)],
                      compresser=lambda c: c) == []

    def test_une_compression_qui_echoue_est_rapportee(self, tmp_path):
        """Un ffmpeg absent ne doit pas interrompre le rangement des autres."""
        from greffier.application.ranger import ranger

        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-08-01_09h00_vieille")

        def tomber(_chemin):
            raise OSError("ffmpeg introuvable")

        faits = ranger(ou, self.regle_courante(),
                       [("2026-08-01_09h00_vieille", 40.0, True)],
                       compresser=tomber, pour_de_vrai=True)
        assert faits[0].souci
        assert (ou.enregistrements / "2026-08-01_09h00_vieille.wav").exists()

    def test_l_effacement_libere_tout_l_audio(self, tmp_path):
        from greffier.application.ranger import ranger
        from greffier.domaine.retention import Regle

        ou = emplacements(tmp_path)
        poser_une_reunion(ou, "2026-01-01_09h00_ancienne")
        audio = ou.enregistrements / "2026-01-01_09h00_ancienne.wav"
        faits = ranger(ou, Regle(compresser_apres=7, effacer_apres=90),
                       [("2026-01-01_09h00_ancienne", 200.0, True)],
                       compresser=lambda c: c, pour_de_vrai=True)
        assert faits[0].geste == "effacer"
        assert not audio.exists()
        assert (ou.transcriptions / "2026-01-01_09h00_ancienne.txt").exists(), (
            "la transcription porte le travail : elle reste"
        )


class TestToutCeQuiAppartientALaReunion:
    """Effacer une réunion doit tout prendre : sinon il reste des données.

    Les questions posées, la conversation tenue et les documents fournis
    vivaient hors de l'énumération : « effacer » laissait derrière lui ce que
    la réunion avait produit de plus bavard.
    """

    def poser(self, tmp_path, identifiant="reunion-1"):
        from greffier.application.ranger import Emplacements

        for nom in ("enregistrements", "reunions", "transcriptions",
                    "comptes-rendus", "direct", "propositions", "questions",
                    "conversations", "pieces"):
            (tmp_path / nom).mkdir()
        (tmp_path / "questions" / f"{identifiant}.jsonl").write_text("{}\n")
        (tmp_path / "conversations" / f"{identifiant}.jsonl").write_text("{}\n")
        (tmp_path / "pieces" / identifiant).mkdir()
        (tmp_path / "pieces" / identifiant / "ordre-du-jour.txt").write_text("x")
        return Emplacements(
            reunions=tmp_path / "reunions",
            enregistrements=tmp_path / "enregistrements",
            transcriptions=tmp_path / "transcriptions",
            comptes_rendus=tmp_path / "comptes-rendus",
            direct=tmp_path / "direct",
            propositions=tmp_path / "propositions",
            questions=tmp_path / "questions",
            conversations=tmp_path / "conversations",
            pieces=tmp_path / "pieces",
        )

    def test_les_questions_et_la_conversation_sont_comptees(self, tmp_path):
        from greffier.application.ranger import pieces_de

        quoi = {p.quoi for p in pieces_de(self.poser(tmp_path), "reunion-1")}
        assert "questions posées" in quoi
        assert "conversation avec l'assistant" in quoi

    def test_les_documents_fournis_sont_comptes(self, tmp_path):
        from greffier.application.ranger import pieces_de

        trouvees = pieces_de(self.poser(tmp_path), "reunion-1")
        assert any("document fourni" in p.quoi for p in trouvees)

    def test_oublier_retire_aussi_le_dossier_des_documents(self, tmp_path):
        """Un dossier vide laisse croire qu'il reste quelque chose."""
        from greffier.application.ranger import oublier

        ou = self.poser(tmp_path)
        oublier(ou, "reunion-1")
        assert not (tmp_path / "pieces" / "reunion-1").exists()
        assert not (tmp_path / "questions" / "reunion-1.jsonl").exists()

    def test_les_emplacements_facultatifs_restent_facultatifs(self, tmp_path):
        """Les appels existants construisent six champs, pas neuf."""
        from greffier.application.ranger import Emplacements, pieces_de

        ou = Emplacements(
            reunions=tmp_path, enregistrements=tmp_path, transcriptions=tmp_path,
            comptes_rendus=tmp_path, direct=tmp_path, propositions=tmp_path,
        )
        assert pieces_de(ou, "reunion-1") == []
