"""La langue devient un choix, et ce choix doit survivre.

Trois pièges, dont un seul est visible.

Le premier : la langue écrite dans le `.env`. L'ordre de priorité est
environnement, puis `.env`, puis `config.toml` ; une langue posée dans le `.env`
primerait pour toujours et rendrait la liste déroulante des Réglages inerte,
sans qu'aucune erreur ne le dise.

Le deuxième : un champ absent de `SECTIONS`. Le fichier de configuration est
régénéré, pas rustiné, donc un champ oublié là est perdu au premier
enregistrement depuis la fenêtre.

Le troisième : les consignes de rédaction. Cent lignes d'ajustements gagnés sur
de vraies réunions — le français doit en ressortir caractère pour caractère.
"""

from greffier.adaptateurs.assistant_terminal import Reponses
from greffier.adaptateurs.configuration import SECTIONS, Config, rendre
from greffier.adaptateurs.redaction_claude import CONSIGNES, consignes
from greffier.adaptateurs.redaction_ollama import CONSIGNES as CONSIGNES_OLLAMA
from greffier.adaptateurs.redaction_ollama import consignes as consignes_ollama
from greffier.domaine.langues import LANGUES, eprouvee, libelle, nom_de


class TestLaLangueNAtterritJamaisDansLeEnv:
    def test_elle_va_dans_les_reglages(self):
        reponses = Reponses()
        reponses.regler("transcription", "langue", "de")

        assert reponses.reglages == {"transcription": {"langue": "de"}}

    def test_et_pas_dans_le_env(self):
        """Sinon la liste déroulante des Réglages ne pourrait plus rien changer."""
        reponses = Reponses()
        reponses.regler("transcription", "langue", "de")
        reponses.regler("compte_rendu", "langue", "fr")

        assert "LANGUE" not in reponses.rendre_env().upper()
        assert reponses.valeurs == {}


class TestLaLangueDuCompteRenduSurvit:
    def test_elle_est_dans_les_sections_reecrites(self):
        """Le fichier est régénéré : un champ absent d'ici est perdu."""
        assert "langue" in SECTIONS["compte_rendu"]

    def test_elle_se_retrouve_dans_le_fichier_ecrit(self):
        config = Config()
        config.compte_rendu.langue = "en"

        assert 'langue = "en"' in rendre(config) or "langue = 'en'" in rendre(config)

    def test_vide_par_defaut_veut_dire_celle_de_la_reunion(self):
        assert Config().compte_rendu.langue == ""


class TestLesConsignesSuiventLaLangue:
    def test_le_francais_est_inchange_caractere_pour_caractere(self):
        assert consignes("") == CONSIGNES
        assert consignes("fr") == CONSIGNES
        assert consignes_ollama("fr") == CONSIGNES_OLLAMA

    def test_une_autre_langue_est_dictee_en_tete(self):
        assert consignes("en").startswith("Rédige entièrement en Anglais")

    def test_et_rappelee_a_la_fin(self):
        """Un modèle qui lit cent lignes de français y retombe volontiers."""
        assert consignes("en").rstrip().endswith("le compte rendu s'écrit en Anglais.")

    def test_la_mention_du_francais_disparait(self):
        assert "en français" not in consignes("de")
        assert "Allemand" in consignes("de")


class TestLeCatalogueDitCeQueChaqueLangueRecoit:
    def test_le_francais_est_eprouve(self):
        assert eprouvee("fr")

    def test_les_autres_ne_le_sont_pas_et_le_disent(self):
        assert not eprouvee("en")
        assert "à nommer à la main" in libelle("en")

    def test_la_detection_automatique_ne_promet_rien_de_faux(self):
        assert libelle("") == "Détection automatique"

    def test_aucun_code_en_double(self):
        codes = [code for code, _ in LANGUES]
        assert len(codes) == len(set(codes))

    def test_un_code_inconnu_se_rend_lui_meme(self):
        assert nom_de("xx") == "xx"
