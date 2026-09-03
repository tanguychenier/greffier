"""Régénérer la rédaction seule, depuis un fichier maître déjà écrit."""

from datetime import UTC, datetime
from pathlib import Path

from greffier.adaptateurs.depot_fichiers import ReunionEnregistree
from greffier.application.restituer import regenerer_compte_rendu, rendre_transcription
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole


def reunion_type(**remplacements) -> ReunionEnregistree:
    defauts = dict(
        identifiant="2026-08-24_reunion",
        audio=Path("/tmp/r.wav"),
        traitee_le=datetime.now(UTC),
        duree=100.0,
        repliques=[Replique(Intervalle(0, 40), "bonjour à tous", "1"),
                   Replique(Intervalle(60, 95), "au revoir", "2")],
        tours=[TourDeParole(Intervalle(0, 40), "1"), TourDeParole(Intervalle(60, 95), "2")],
        noms={"1": "Josiane"},
        propositions={},
        avertissements=[],
        evenements_materiel=[],
    )
    defauts.update(remplacements)
    return ReunionEnregistree(**defauts)


class RedacteurFactice:
    def __init__(self) -> None:
        self.recu: str | None = None

    def rediger(self, transcription: str) -> str:
        self.recu = transcription
        return "# Compte rendu\n\nTout va bien."


class TestRendreLaTranscription:
    def test_fonctionne_directement_sur_une_reunion_relue(self) -> None:
        """`ReunionEnregistree` doit satisfaire le même protocole que
        `Resultat`, sans conversion : c'est ce qui permet de rejouer la
        rédaction sans repasser par un traitement complet."""
        texte = rendre_transcription(reunion_type())
        assert "[Josiane]" in texte
        assert "[Personne 2]" in texte


class TestRegenererLeCompteRendu:
    def test_le_redacteur_recoit_les_noms_a_jour(self) -> None:
        reunion = reunion_type(noms={"1": "Josiane", "2": "Marc"})
        redacteur = RedacteurFactice()
        regenerer_compte_rendu(reunion, redacteur)
        assert "[Josiane]" in redacteur.recu
        assert "[Marc]" in redacteur.recu

    def test_le_texte_rendu_est_celui_du_redacteur(self) -> None:
        assert (
            regenerer_compte_rendu(reunion_type(), RedacteurFactice())
            == "# Compte rendu\n\nTout va bien."
        )

    def test_les_evenements_materiel_survivent_a_la_regeneration(self) -> None:
        """Le défaut visé : régénérer ne doit pas rendre le compte rendu moins
        fiable que l'original en perdant ce que la veille du matériel savait."""
        reunion = reunion_type(evenements_materiel=["casque branché à 12:03"])
        redacteur = RedacteurFactice()
        regenerer_compte_rendu(reunion, redacteur)
        assert "casque branché à 12:03" in redacteur.recu
