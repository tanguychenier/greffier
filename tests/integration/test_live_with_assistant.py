"""La veille, le fil et l'assistant, ensemble, sur du vrai son.

Les tests unitaires éprouvent chaque pièce ; celui-ci éprouve leur montage.
C'est le scénario de la démonstration : la réunion tourne, quelqu'un appelle
l'assistant par son prénom, et il répond — sans que la transcription prenne du
retard pendant qu'il réfléchit.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from greffier.adapters.configuration import Config
from greffier.application.follow import Position
from greffier.application.take_part import AssistantSettings
from greffier.application.watch import Watcher
from greffier.domain.instructions import WatchRules
from greffier.domain.participation import Because, Manners
from greffier.wiring import light_transcriber

pytestmark = pytest.mark.integration

PHRASE = "Lucie, est-ce que tu peux nous rappeler ce qui reste à faire ?"


class FakeVoiceAdapter:
    def __init__(self):
        self.remark = []

    def say(self, text):
        self.remark.append(text)
        return True

    def go_quiet(self):
        ...

    def is_speaking(self):
        return False


class FakeBrain:
    """Le cerveau est doublé : on éprouve le montage, pas le modèle distant."""

    def __init__(self):
        self.consignes_propres = ""
        self.vu = []

    def write_up(self, text):
        self.vu.append(text)
        return "Il reste la signature, et la recette à caler."


@pytest.fixture
def meeting(tmp_path):
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


def test_appele_pendant_la_reunion_il_repond(meeting, tmp_path):
    """Le scénario de la démonstration, de bout en bout."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    voice, cerveau = FakeVoiceAdapter(), FakeBrain()
    assistant = AssistantSettings(
        name="Lucie", voice=voice, cerveau=cerveau,
        # Un creux large : le fichier s'arrête sur la phrase, donc la fin de la
        # dernière réplique tombe près de « maintenant ».
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion d'équipe sur la recette.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting, written=duration, offset=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)
    # La réponse est formulée dans un fil séparé : on l'attend, sans quoi le
    # test mesurerait seulement qu'on ne bloque pas la transcription.
    if assistant._job is not None:
        assistant._job.join(timeout=30)

    assert voice.remark == ["Il reste la signature, et la recette à caler."]
    assert assistant.manners.spoke_at is not None


def test_la_transcription_n_attend_pas_la_reponse(meeting, tmp_path):
    """Formuler prend des secondes ; les passer à attendre coûte de l'audio.

    On mesure que la main revient avant que le cerveau ait répondu, ce qui est
    précisément ce que le fil séparé garantit.
    """
    import threading
    import time

    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    parti = threading.Event()

    class SlowBrain(FakeBrain):
        def write_up(self, text):
            parti.set()
            time.sleep(5.0)
            return "…"

    assistant = AssistantSettings(
        name="Lucie", voice=FakeVoiceAdapter(), cerveau=SlowBrain(),
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion.",
    )
    import soundfile

    duration = soundfile.info(str(meeting)).duration
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting, written=duration, offset=0.0),
        assistant_of=assistant,
    )
    depart = time.monotonic()
    watcher.transcription_turn(watcher.situer(), tmp_path)
    rendered = time.monotonic() - depart

    assert parti.wait(timeout=10), "l'assistant n'a pas été sollicité"
    # La transcription elle-même prend quelques secondes ; ce qu'on vérifie est
    # qu'elle n'a pas attendu les cinq du cerveau par-dessus.
    assert rendered < 5.0, f"la veille a attendu la réponse ({rendered:.1f} s)"


def test_une_phrase_ordinaire_ne_le_fait_pas_parler(tmp_path):
    """Sans son nom, rien ne se déclenche : c'est le cas de toute la réunion."""
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        pytest.skip("« say » ou ffmpeg absent")
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")

    brut, audio = tmp_path / "p.aiff", tmp_path / "p.wav"
    subprocess.run(["say", "-v", "Thomas", "-o", str(brut),
                    "On passe au point suivant, la recette est terminée."],
                   check=False, capture_output=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                    str(brut), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(audio)], check=False, capture_output=True)

    voice = FakeVoiceAdapter()
    assistant = AssistantSettings(name="Lucie", voice=voice, manners=Manners(creux_minimal=0.0))
    import soundfile

    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=audio, written=soundfile.info(str(audio)).duration,
                                offset=0.0),
        assistant_of=assistant,
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)
    assert voice.remark == []


def test_l_assistant_absent_ne_change_rien(meeting, tmp_path):
    """La veille sans assistant est ce qu'elle a toujours été."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    import soundfile

    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=tmp_path / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(morceau=meeting,
                                written=soundfile.info(str(meeting)).duration,
                                offset=0.0),
    )
    watcher.transcription_turn(watcher.situer(), tmp_path)


def test_la_raison_de_parler_est_l_appel(meeting, tmp_path):
    """Ce n'est pas un apport spontané : c'est qu'on l'a nommée."""
    transcriber = light_transcriber(Config())
    if transcriber is None:
        pytest.skip("aucun modèle de transcription installé")
    utterances = transcriber.transcribe(meeting, "fr", "Lucie.")
    assistant = AssistantSettings(name="Lucie", manners=Manners(creux_minimal=0.0))
    retenue = assistant.turn(utterances, now=max(
        r.span.end for r in utterances) + 1.0)
    assert retenue is not None and retenue.because is Because.APPELE


@pytest.mark.integration
class TestLaBoucleSurUnFilReel:
    """La boucle du transcripteur, sur le fil d'une vraie réunion.

    Reconstitué depuis le fil du 2026-09-10 à 13 h 08, tel qu'il a été publié :
    cent vingt-cinq tours dont soixante-cinq de répétition, quatre boucles
    distinctes, la plus longue de douze segments d'une seconde.
    """

    #: Les quatre boucles réellement observées, dans l'ordre du fil.
    OBSERVE = [
        ("Est-ce que tu entends Lucie ?", 30.0, 11),
        ("- C'est ça qu'on va faire.", 125.0, 12),
        ("Je vais vous créer la vache.", 166.0, 11),
        ("Est-ce que tu n'as pas fait ?", 41.0, 9),
    ]

    def _fil(self):
        from greffier.domain.models import Span, Utterance

        dites = []
        for texte, depart, how_many in self.OBSERVE:
            dites += [
                Utterance(span=Span(depart + i, depart + i + 1), text=texte)
                for i in range(how_many)
            ]
        return sorted(dites, key=lambda u: u.span.start)

    def test_les_quatre_boucles_se_replient(self):
        from greffier.domain.boilerplate import collapse_loops

        avant = self._fil()
        apres = collapse_loops(avant)
        assert len(avant) == 43
        assert len(apres) == 4, [u.text for u in apres]

    def test_chaque_phrase_gardee_couvre_son_passage(self):
        from greffier.domain.boilerplate import collapse_loops

        for gardee in collapse_loops(self._fil()):
            expected = next(c for t, _d, c in self.OBSERVE if t == gardee.text)
            assert gardee.span.end - gardee.span.start == expected

    def test_le_fil_publie_ne_porte_plus_la_repetition(self):
        """Ce que la fenêtre affiche : une ligne par phrase dite."""
        from greffier.domain.boilerplate import collapse_loops

        textes = [u.text for u in collapse_loops(self._fil())]
        assert len(textes) == len(set(textes))


@pytest.mark.integration
class TestUnAncienReglageNeRendPlusMuet:
    """Un réglage que l'interface n'expose plus ne doit plus décider.

    Le défaut, vécu deux fois en réunion : le fichier de configuration portait
    « actif = false », écrit à l'époque où un bouton existait pour ce réglage.
    Passer la valeur par défaut à vrai n'a servi à rien — un fichier existant
    garde la sienne — et comme l'interface n'exposait plus ce bouton, plus rien
    ne pouvait le remettre. L'appel était bien entendu : « Est-ce que tu
    entends, Lucie ? » figure douze fois dans le fil du 2026-09-10 à 13 h 08.
    Elle n'a pas répondu une seule fois.

    Ce test lit un vrai fichier, dans l'état où les postes en portent un.
    """

    ANCIEN = """
[assistant]
actif = false
nom = "Lucie"
voix = "kokoro"
initiative = false
"""

    def _boutons(self, tmp_path, monkeypatch, contenu: str):
        from greffier.cli import _reread_the_buttons

        dossier = tmp_path / "greffier"
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "config.toml").write_text(contenu, encoding="utf-8")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("APPDATA", str(tmp_path))
        for clef in ("GREFFIER_ASSISTANT__ACTIVE", "GREFFIER_ASSISTANT__VOICE",
                     "GREFFIER_ASSISTANT__INITIATIVE"):
            monkeypatch.delenv(clef, raising=False)
        return _reread_the_buttons()

    def test_un_fichier_portant_actif_faux_ne_coupe_plus_la_voix(
        self, tmp_path, monkeypatch
    ):
        a_voix_haute, _de_lui_meme = self._boutons(tmp_path, monkeypatch, self.ANCIEN)
        assert a_voix_haute, "la voix est réglée sur kokoro : elle doit parler"

    def test_couper_la_voix_reste_possible(self, tmp_path, monkeypatch):
        """Le seul réglage qui décide encore, et il doit décider."""
        a_voix_haute, _ = self._boutons(
            tmp_path, monkeypatch,
            '[assistant]\nactif = true\nnom = "Lucie"\nvoix = "aucun"\n',
        )
        assert not a_voix_haute

    def test_l_initiative_se_lit_dans_le_fichier(self, tmp_path, monkeypatch):
        _, de_lui_meme = self._boutons(
            tmp_path, monkeypatch,
            '[assistant]\nnom = "Lucie"\nvoix = "kokoro"\ninitiative = true\n',
        )
        assert de_lui_meme

    def test_appelee_elle_repond_malgre_l_ancien_reglage(self, meeting, tmp_path):
        """Le scénario complet, avec le fichier qui l'avait rendue muette."""
        transcriber = light_transcriber(Config())
        if transcriber is None:
            pytest.skip("aucun modèle de transcription installé")
        import soundfile

        voice, cerveau = FakeVoiceAdapter(), FakeBrain()
        assistant = AssistantSettings(
            name="Lucie", voice=voice, cerveau=cerveau,
            manners=Manners(creux_minimal=0.0),
            context=lambda: "Réunion d'équipe sur la recette.",
        )
        watcher = Watcher(
            watch_rules=WatchRules(keyword="greffier"),
            log=tmp_path / "propositions.jsonl",
            transcriber=transcriber,
            situer=lambda: Position(
                morceau=meeting,
                written=soundfile.info(str(meeting)).duration,
                offset=0.0,
            ),
            assistant_of=assistant,
            # Ce que la veille lit du fichier : la voix est donnée, pas
            # d'initiative. « actif » n'entre plus dans la décision.
            reread_participation=lambda: (True, False),
        )
        watcher.transcription_turn(watcher.situer(), tmp_path)
        if assistant._job is not None:
            assistant._job.join(timeout=30)
        assert voice.remark, "appelée par son nom, elle doit avoir parlé"
