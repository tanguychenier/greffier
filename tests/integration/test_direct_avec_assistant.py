"""La veille, le fil et l'assistant, ensemble, sur du vrai son.

Les tests unitaires éprouvent chaque pièce ; celui-ci éprouve leur montage.
C'est le scénario de la démonstration : la réunion tourne, quelqu'un appelle
l'assistant par son prénom, et il répond — sans que la transcription prenne du
retard pendant qu'il réfléchit.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from greffier.adaptateurs.configuration import Config
from greffier.application.participer import Participant
from greffier.application.suivre import Position
from greffier.application.veiller import Veilleur
from greffier.composition import transcripteur_leger
from greffier.domaine.instructions import Veille
from greffier.domaine.participation import Politique, Raison

pytestmark = pytest.mark.integration

PHRASE = "Lucie, est-ce que tu peux nous rappeler ce qui reste à faire ?"


class VoixFactice:
    def __init__(self):
        self.propos = []

    def dire(self, texte):
        self.propos.append(texte)
        return True

    def se_taire(self):
        ...

    def parle(self):
        return False


class CerveauFactice:
    """Le cerveau est doublé : on éprouve le montage, pas le modèle distant."""

    def __init__(self):
        self.consignes_propres = ""
        self.vu = []

    def rediger(self, texte):
        self.vu.append(texte)
        return "Il reste la signature, et la recette à caler."


@pytest.fixture
def reunion(tmp_path):
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        pytest.skip("« say » ou ffmpeg absent")
    brut = tmp_path / "phrase.aiff"
    audio = tmp_path / "reunion.wav"
    subprocess.run(["say", "-v", "Thomas", "-o", str(brut), PHRASE],
                   check=False, capture_output=True)
    if not brut.exists():
        pytest.skip("synthèse impossible")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio)],
        check=False, capture_output=True,
    )
    return audio


def test_appele_pendant_la_reunion_il_repond(reunion, tmp_path):
    """Le scénario de la démonstration, de bout en bout."""
    transcripteur = transcripteur_leger(Config())
    if transcripteur is None:
        pytest.skip("aucun modèle de transcription installé")

    voix, cerveau = VoixFactice(), CerveauFactice()
    assistant = Participant(
        nom="Lucie", voix=voix, cerveau=cerveau,
        # Un creux large : le fichier s'arrête sur la phrase, donc la fin de la
        # dernière réplique tombe près de « maintenant ».
        politique=Politique(creux_minimal=0.0),
        contexte=lambda: "Réunion d'équipe sur la recette.",
    )
    import soundfile

    duree = soundfile.info(str(reunion)).duration
    veilleur = Veilleur(
        veille=Veille(mot_cle="greffier"),
        journal=tmp_path / "propositions.jsonl",
        transcripteur=transcripteur,
        situer=lambda: Position(morceau=reunion, ecrit=duree, decalage=0.0),
        participant=assistant,
    )
    veilleur.tour_transcription(veilleur.situer(), tmp_path)
    # La réponse est formulée dans un fil séparé : on l'attend, sans quoi le
    # test mesurerait seulement qu'on ne bloque pas la transcription.
    if assistant._travail is not None:
        assistant._travail.join(timeout=30)

    assert voix.propos == ["Il reste la signature, et la recette à caler."]
    assert assistant.politique.parle_le is not None


def test_la_transcription_n_attend_pas_la_reponse(reunion, tmp_path):
    """Formuler prend des secondes ; les passer à attendre coûte de l'audio.

    On mesure que la main revient avant que le cerveau ait répondu, ce qui est
    précisément ce que le fil séparé garantit.
    """
    import threading
    import time

    transcripteur = transcripteur_leger(Config())
    if transcripteur is None:
        pytest.skip("aucun modèle de transcription installé")

    parti = threading.Event()

    class CerveauLent(CerveauFactice):
        def rediger(self, texte):
            parti.set()
            time.sleep(5.0)
            return "…"

    assistant = Participant(
        nom="Lucie", voix=VoixFactice(), cerveau=CerveauLent(),
        politique=Politique(creux_minimal=0.0),
        contexte=lambda: "Réunion.",
    )
    import soundfile

    duree = soundfile.info(str(reunion)).duration
    veilleur = Veilleur(
        veille=Veille(mot_cle="greffier"),
        journal=tmp_path / "propositions.jsonl",
        transcripteur=transcripteur,
        situer=lambda: Position(morceau=reunion, ecrit=duree, decalage=0.0),
        participant=assistant,
    )
    depart = time.monotonic()
    veilleur.tour_transcription(veilleur.situer(), tmp_path)
    rendu = time.monotonic() - depart

    assert parti.wait(timeout=10), "l'assistant n'a pas été sollicité"
    # La transcription elle-même prend quelques secondes ; ce qu'on vérifie est
    # qu'elle n'a pas attendu les cinq du cerveau par-dessus.
    assert rendu < 5.0, f"la veille a attendu la réponse ({rendu:.1f} s)"


def test_une_phrase_ordinaire_ne_le_fait_pas_parler(tmp_path):
    """Sans son nom, rien ne se déclenche : c'est le cas de toute la réunion."""
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        pytest.skip("« say » ou ffmpeg absent")
    transcripteur = transcripteur_leger(Config())
    if transcripteur is None:
        pytest.skip("aucun modèle de transcription installé")

    brut, audio = tmp_path / "p.aiff", tmp_path / "p.wav"
    subprocess.run(["say", "-v", "Thomas", "-o", str(brut),
                    "On passe au point suivant, la recette est terminée."],
                   check=False, capture_output=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                    str(brut), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(audio)], check=False, capture_output=True)

    voix = VoixFactice()
    assistant = Participant(nom="Lucie", voix=voix, politique=Politique(creux_minimal=0.0))
    import soundfile

    veilleur = Veilleur(
        veille=Veille(mot_cle="greffier"),
        journal=tmp_path / "propositions.jsonl",
        transcripteur=transcripteur,
        situer=lambda: Position(morceau=audio, ecrit=soundfile.info(str(audio)).duration,
                                decalage=0.0),
        participant=assistant,
    )
    veilleur.tour_transcription(veilleur.situer(), tmp_path)
    assert voix.propos == []


def test_l_assistant_absent_ne_change_rien(reunion, tmp_path):
    """La veille sans assistant est ce qu'elle a toujours été."""
    transcripteur = transcripteur_leger(Config())
    if transcripteur is None:
        pytest.skip("aucun modèle de transcription installé")
    import soundfile

    veilleur = Veilleur(
        veille=Veille(mot_cle="greffier"),
        journal=tmp_path / "propositions.jsonl",
        transcripteur=transcripteur,
        situer=lambda: Position(morceau=reunion,
                                ecrit=soundfile.info(str(reunion)).duration,
                                decalage=0.0),
    )
    veilleur.tour_transcription(veilleur.situer(), tmp_path)


def test_la_raison_de_parler_est_l_appel(reunion, tmp_path):
    """Ce n'est pas un apport spontané : c'est qu'on l'a nommée."""
    transcripteur = transcripteur_leger(Config())
    if transcripteur is None:
        pytest.skip("aucun modèle de transcription installé")
    repliques = transcripteur.transcrire(reunion, "fr", "Lucie.")
    assistant = Participant(nom="Lucie", politique=Politique(creux_minimal=0.0))
    retenue = assistant.tour(repliques, maintenant=max(
        r.intervalle.fin for r in repliques) + 1.0)
    assert retenue is not None and retenue.raison is Raison.APPELE
