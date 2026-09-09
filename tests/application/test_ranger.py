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
