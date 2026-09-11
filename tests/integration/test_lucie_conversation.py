"""A whole conversation with the assistant, in real sound.

The unit tests say each rule is right. They do not say what happens when the
rules are chained: it answers, its answer leaves through the loudspeaker, the
capture takes it back in, the transcriber returns it mangled, and the thread
gives it one more voice. That is where the loop was born, and no double would
have shown it.

The harness builds a real meeting file with the system's speech synthesis, one
voice per person, and **feeds the assistant's answer back into the audio**,
which is what a loudspeaker does in a room. Then it runs the real watch, slice
by slice, with the real transcriber.

The brain is a double: the point is not to test the model, it is to test the
loop around it.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from greffier.adapters.configuration import Config
from greffier.application.follow import Position
from greffier.application.take_part import AssistantSettings
from greffier.application.watch import Watcher
from greffier.domain.instructions import WatchRules
from greffier.domain.participation import Manners
from greffier.wiring import light_transcriber

NAME = "Lucie"

#: Deux voix du système, pour que les personnes se distinguent à l'oreille.
VOIX_DE_LA_SALLE = "Thomas"
VOIX_DE_L_ASSISTANTE = "Amélie"


def _dispo() -> bool:
    return shutil.which("say") is not None and shutil.which("ffmpeg") is not None


def _synthetiser(voice: str, text: str, cible: Path) -> Path | None:
    """Une phrase prononcée, en wav 16 kHz mono."""
    brut = cible.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(brut), text],
                   check=False, capture_output=True)
    if not brut.exists():
        return None
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(cible)],
        check=False, capture_output=True,
    )
    return cible if cible.exists() else None


def _silence(secondes: float, cible: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=16000:cl=mono", "-t", str(secondes),
         "-c:a", "pcm_s16le", str(cible)],
        check=False, capture_output=True,
    )
    return cible


def _coller(morceaux: list[Path], cible: Path) -> Path:
    """Glues wav files end to end, like one continuous recording."""
    liste = cible.with_suffix(".txt")
    liste.write_text(
        "".join(f"file '{p}'\n" for p in morceaux), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", str(liste), "-c", "copy", str(cible)],
        check=False, capture_output=True,
    )
    return cible


@dataclass
class HautParleur:
    """The assistant's voice, and what it leaves in the room.

    It keeps what was pronounced, which is what gets checked, and the harness then
    feeds it back into the audio of the meeting, because that is exactly what a
    loudspeaker does.
    """

    dites: list[str] = field(default_factory=list)
    parle_encore: bool = False
    coupures: int = 0

    def say(self, text: str) -> bool:
        if self.parle_encore:
            # Ce que fait la vraie voix depuis le correctif : elle refuse
            # plutôt que de se couper elle-même.
            self.coupures += 1
            return False
        self.dites.append(text)
        return True

    def go_quiet(self) -> None:
        self.parle_encore = False

    def is_speaking(self) -> bool:
        return self.parle_encore


@dataclass
class CerveauDeTest:
    """Répond de façon déterministe, et compte combien de fois on l'appelle."""

    reponses: list[str] = field(default_factory=list)
    demandes: list[str] = field(default_factory=list)
    defaut: str = "Je n'ai pas la réponse dans ce qui a été dit."

    def write_up(self, demande: str) -> str:
        self.demandes.append(demande)
        if self.reponses:
            return self.reponses.pop(0)
        return self.defaut


@dataclass
class Reunion:
    """A recording that grows, as it does during a real meeting."""

    dossier: Path
    morceaux: list[Path] = field(default_factory=list)
    rang: int = 0
    dernier_tour: int = 0

    #: Une tranche plus courte que ceci n'est pas transcrite : le modèle y
    #: invente plus qu'il n'entend. Le harnais complète donc chaque prise par
    #: du silence, comme une vraie pièce entre deux phrases.
    TRANCHE_UTILE = 3.4

    def dire(self, voice: str, text: str, avant: float = 0.6) -> None:
        self.rang += 1
        if avant:
            self.morceaux.append(
                _silence(avant, self.dossier / f"blanc{self.rang}.wav")
            )
        piece = _synthetiser(voice, text, self.dossier / f"dit{self.rang}.wav")
        if piece is None:
            pytest.skip("synthèse impossible")
        self.morceaux.append(piece)
        self.respirer()

    def respirer(self) -> None:
        """Pads the take so that the slice is worth transcribing."""
        import soundfile

        since = sum(
            float(soundfile.info(str(p)).duration)
            for p in self.morceaux[self.dernier_tour:]
        )
        if since < self.TRANCHE_UTILE:
            self.rang += 1
            self.morceaux.append(_silence(
                self.TRANCHE_UTILE - since,
                self.dossier / f"souffle{self.rang}.wav",
            ))
        self.dernier_tour = len(self.morceaux)

    def audio(self) -> Path:
        return _coller(self.morceaux, self.dossier / "reunion.wav")

    def duree(self) -> float:
        import soundfile

        return float(soundfile.info(str(self.audio())).duration)


@pytest.fixture(scope="module")
def transcriber():
    if not _dispo():
        pytest.skip("« say » ou ffmpeg absent")
    outil = light_transcriber(Config())
    if outil is None:
        pytest.skip("aucun modèle de transcription installé")
    return outil


def _veilleur(reunion: Reunion, assistante: AssistantSettings,
              transcriber, dossier: Path) -> Watcher:
    return Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=dossier / "propositions.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(
            morceau=reunion.audio(), written=reunion.duree(), offset=0.0
        ),
        assistant_of=assistante,
        reread_participation=lambda: (True, False),
    )


def _assistante(cerveau: CerveauDeTest, voice: HautParleur) -> AssistantSettings:
    return AssistantSettings(
        name=NAME, cerveau=cerveau, voice=voice,
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion d'équipe sur la recette et la migration.",
    )


def _a_turn(veilleur: Watcher, assistante: AssistantSettings,
             dossier: Path) -> None:
    """One slice, then a wait for the answer: it is phrased in another thread."""
    where_in = veilleur.situer()
    assert where_in is not None
    veilleur.transcription_turn(where_in, dossier)
    if assistante._job is not None:
        assistante._job.join(timeout=60)


@pytest.mark.integration
class TestAWholeConversation:
    """What happens when the turns are chained, and not on one sentence."""

    def test_called_then_its_answer_comes_back_and_it_stays_quiet(
        self, transcriber, tmp_path
    ):
        """The defect as lived, reproduced and then proven impossible.

        It answers, its answer comes back out of the loudspeaker, the capture takes it
        in, and it has to stay quiet. Before, it read its own name there and set off
        again, fifteen times in fifteen seconds.
        """
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE,
                     f"{NAME}, est-ce que tu peux faire des recherches sur Internet ?")
        cerveau = CerveauDeTest(reponses=[
            "Je peux chercher, d'après la documentation de l'éditeur."
        ])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, voice.dites
        assert NAME not in voice.dites[0], "son nom ne doit jamais sortir"

        # Le haut-parleur : ce qu'elle a dit entre dans la pièce.
        reunion.dire(VOIX_DE_L_ASSISTANTE, voice.dites[0])
        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, (
            "elle a répondu à sa propre voix : " + str(voice.dites)
        )

    def test_the_room_is_still_heard_after_it_has_spoken(
        self, transcriber, tmp_path
    ):
        """The other half: the guard must not make it deaf."""
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE, f"{NAME}, où en est la recette ?")
        cerveau = CerveauDeTest(reponses=[
            "La recette est décalée à jeudi.",
            "Il reste deux anomalies bloquantes.",
        ])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, voice.dites

        reunion.dire(VOIX_DE_L_ASSISTANTE, voice.dites[0])
        reunion.dire(VOIX_DE_LA_SALLE, f"Et les anomalies {NAME} ?")
        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 2, (
            "une nouvelle question de la salle doit obtenir une réponse : "
            + str(voice.dites)
        )

    def test_it_does_not_answer_when_nobody_calls_it(
        self, transcriber, tmp_path
    ):
        """An assistant that answers everything is as useless as a deaf one."""
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE,
                     "On passe au point suivant, la recette est calée pour jeudi.")
        cerveau = CerveauDeTest()
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _a_turn(veilleur, assistante, tmp_path)
        assert voice.dites == [], voice.dites
        assert cerveau.demandes == [], "le modèle n'a même pas à être appelé"

    def test_it_does_not_cut_itself_off_while_still_speaking(
        self, transcriber, tmp_path
    ):
        """"Sometimes it starts speaking and it gets cut off."

        Two calls close together: the second must not kill the sentence under way.
        """
        reunion = Reunion(tmp_path)
        reunion.dire(VOIX_DE_LA_SALLE, f"{NAME}, tu nous entends ?")
        cerveau = CerveauDeTest(reponses=["Oui, je vous entends très bien."])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1

        # Elle parle encore quand la question suivante arrive.
        voice.parle_encore = True
        reunion.dire(VOIX_DE_LA_SALLE,
                     f"{NAME}, et où en est la migration en Symfony sept ?")
        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) == 1, "rien de neuf n'a été prononcé"
        assert voice.coupures >= 1, "le refus doit avoir eu lieu"
        assert voice.parle_encore, "la phrase en cours n'a pas été coupée"

    def test_the_transcriber_loop_does_not_multiply_it(
        self, transcriber, tmp_path
    ):
        """The same question repeated gets one answer only."""
        reunion = Reunion(tmp_path)
        for _ in range(3):
            reunion.dire(VOIX_DE_LA_SALLE, f"{NAME}, tu peux nous rappeler la date ?",
                         avant=0.15)
        cerveau = CerveauDeTest(reponses=["C'est jeudi."])
        voice = HautParleur()
        assistante = _assistante(cerveau, voice)
        veilleur = _veilleur(reunion, assistante, transcriber, tmp_path)

        _a_turn(veilleur, assistante, tmp_path)
        assert len(voice.dites) <= 1, voice.dites

    def test_a_participant_restating_their_idea_is_heard(
        self, transcriber, tmp_path
    ):
        """Le risque du garde par les mots : prendre un humain pour elle."""
        from greffier.domain.participation import own_words

        assistante = _assistante(CerveauDeTest(), HautParleur())
        assistante.its_own_words.append((0.0, own_words("La recette est décalée à jeudi.")))
        from greffier.domain.models import Span, Utterance

        humain = Utterance(
            span=Span(300.0, 306.0),
            text="je propose plutôt de caler la recette mardi avec Pascal",
        )
        assert not assistante._is_his_own(humain, 310.0)
