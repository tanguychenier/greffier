"""Exécuter un dépôt : extraire le son, tirer du contexte d'un document."""


from greffier.application.deposer import (
    CONSIGNES_DOCUMENT,
    LU_AU_PLUS,
    apprendre_du_document,
    executer,
    lire_le_texte,
    outils_presents,
)
from greffier.domaine.depot import Destin, Proposition


class RedacteurFactice:
    def __init__(self, rendu: str) -> None:
        self.rendu = rendu
        self.recu = ""

    def rediger(self, texte: str) -> str:
        self.recu = texte
        return self.rendu


class TestLectureDesDocuments:
    def test_un_texte_brut_se_lit(self, tmp_path):
        fichier = tmp_path / "note.md"
        fichier.write_text("Le circuit FAST remplace le papier.", encoding="utf-8")
        assert "FAST" in lire_le_texte(fichier)

    def test_un_format_inconnu_ne_leve_pas(self, tmp_path):
        fichier = tmp_path / "x.zip"
        fichier.write_bytes(b"PK\\x03\\x04")
        assert lire_le_texte(fichier) == ""

    def test_un_fichier_absent_ne_leve_pas(self, tmp_path):
        assert lire_le_texte(tmp_path / "jamais.md") == ""


class TestApprentissageDepuisUnDocument:
    """Le document n'est pas versé tel quel : on en tire du vocabulaire.

    Un compte rendu de dix pages dans l'amorce du transcripteur la ferait
    tronquer sans prévenir.
    """

    def test_les_entrees_sont_lues(self, tmp_path):
        fichier = tmp_path / "specs.md"
        fichier.write_text("FAST et CASA.", encoding="utf-8")
        redacteur = RedacteurFactice(
            '[{"ecriture": "FAST", "sens": "un circuit", "genre": "terme"},'
            ' {"ecriture": "Morgane", "sens": "pilote", "genre": "personne"}]'
        )
        appris = apprendre_du_document(fichier, redacteur)
        assert ("FAST", "un circuit", "terme") in appris
        assert ("Morgane", "pilote", "personne") in appris

    def test_un_document_vide_n_appelle_pas_le_redacteur(self, tmp_path):
        fichier = tmp_path / "vide.md"
        fichier.write_text("   ", encoding="utf-8")
        redacteur = RedacteurFactice("[]")
        assert apprendre_du_document(fichier, redacteur) == ()
        assert redacteur.recu == ""

    def test_une_reponse_illisible_ne_rend_rien(self, tmp_path):
        fichier = tmp_path / "specs.md"
        fichier.write_text("du texte", encoding="utf-8")
        assert apprendre_du_document(fichier, RedacteurFactice("je ne sais pas")) == ()

    def test_un_bloc_de_code_est_accepte(self, tmp_path):
        fichier = tmp_path / "specs.md"
        fichier.write_text("du texte", encoding="utf-8")
        appris = apprendre_du_document(
            fichier, RedacteurFactice('```json\\n[{"ecriture": "FAST"}]\\n```')
        )
        assert appris == (("FAST", "", "terme"),)

    def test_seul_le_debut_du_document_est_lu(self, tmp_path):
        """Cent pages ne se lisent pas pour en tirer vingt mots."""
        fichier = tmp_path / "gros.md"
        fichier.write_text("x" * (LU_AU_PLUS * 2), encoding="utf-8")
        redacteur = RedacteurFactice("[]")
        apprendre_du_document(fichier, redacteur)
        assert len(redacteur.recu) <= len(CONSIGNES_DOCUMENT) + LU_AU_PLUS

    def test_les_consignes_excluent_les_mots_courants(self):
        aplati = " ".join(CONSIGNES_DOCUMENT.split())
        assert "Pas les mots courants" in aplati
        assert "n'invente pas" in aplati


class TestExecution:
    def test_un_son_est_copie_la_ou_la_chaine_travaille(self, tmp_path):
        """Un fichier déposé depuis une clé USB ne doit pas rester la seule copie."""
        source = tmp_path / "ailleurs" / "reunion.wav"
        source.parent.mkdir()
        source.write_bytes(b"x" * 300_000)
        proposition = Proposition(source, Destin.REUNION, "enregistrement sonore")
        fait = executer(proposition, tmp_path / "enregistrements")
        assert fait.produit is not None and fait.produit.exists()
        assert fait.souci == ""

    def test_un_fichier_bloque_est_rapporte_et_non_tente(self, tmp_path):
        proposition = Proposition(
            tmp_path / "x.mp4", Destin.VIDEO, "vidéo",
            bloque_par="ffmpeg est introuvable",
        )
        fait = executer(proposition, tmp_path / "enregistrements")
        assert "ffmpeg" in fait.souci

    def test_un_document_sans_redacteur_le_dit(self, tmp_path):
        fichier = tmp_path / "note.md"
        fichier.write_text("du texte", encoding="utf-8")
        fait = executer(
            Proposition(fichier, Destin.CONTEXTE, "texte"),
            tmp_path / "enregistrements", redacteur=None,
        )
        assert "aucun rédacteur" in fait.souci


class TestOutils:
    def test_les_outils_presents_sont_ceux_du_poste(self):
        trouves = outils_presents()
        assert isinstance(trouves, frozenset)
        assert trouves <= {"ffmpeg", "pdftotext", "textutil"}
