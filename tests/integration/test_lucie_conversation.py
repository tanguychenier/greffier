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
from tests.integration.prerequisites import (
    the_called_name_is_out_of_reach,
    voices_are_out_of_reach,
)

NAME = "Lucie"

#: Two system voices, so that the people can be told apart by ear.
ROOM_VOICE = "Thomas"
ASSISTANT_VOICE = "Amélie"


def _synthesise(voice: str, text: str, target: Path) -> Path | None:
    """A sentence spoken, as 16 kHz mono wav, by the machine's engine."""
    from make_meeting import speak

    return speak(text, voice, target)


def _silence(total_seconds: float, target: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=16000:cl=mono", "-t", str(total_seconds),
         "-c:a", "pcm_s16le", str(target)],
        check=False, capture_output=True,
    )
    return target


def _glue(chunks: list[Path], target: Path) -> Path:
    """Glues wav files end to end, like one continuous recording."""
    listing_ = target.with_suffix(".txt")
    listing_.write_text(
        "".join(f"file '{p}'\n" for p in chunks), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", str(listing_), "-c", "copy", str(target)],
        check=False, capture_output=True,
    )
    return target


@dataclass
class HautParleur:
    """The assistant's voice, and what it leaves in the room.

    It keeps what was pronounced, which is what gets checked, and the harness then
    feeds it back into the audio of the meeting, because that is exactly what a
    loudspeaker does.
    """

    said_ones: list[str] = field(default_factory=list)
    still_speaking: bool = False
    cuts: int = 0

    def say(self, text: str) -> bool:
        if self.still_speaking:
            # What the real voice does since the fix: it refuses
            # rather than cut itself off.
            self.cuts += 1
            return False
        self.said_ones.append(text)
        return True

    def go_quiet(self) -> None:
        self.still_speaking = False

    def is_speaking(self) -> bool:
        return self.still_speaking


@dataclass
class CerveauDeTest:
    """Répond de façon déterministe, et compte combien de fois on l'appelle."""

    answers: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    defect: str = "Je n'ai pas la réponse dans ce qui a été dit."

    def write_up(self, request: str) -> str:
        self.requests.append(request)
        if self.answers:
            return self.answers.pop(0)
        return self.defect


@dataclass
class Reunion:
    """A recording that grows, as it does during a real meeting."""

    folder: Path
    chunks: list[Path] = field(default_factory=list)
    rang: int = 0
    last_turn: int = 0

    #: A slice shorter than this is not transcribed: the model invents
    #: more than it hears in it. The harness therefore pads every take with
    #: silence, like a real room between two sentences.
    USEFUL_SLICE = 3.4

    def say(self, voice: str, text: str, earlier: float = 0.6) -> None:
        self.rang += 1
        if earlier:
            self.chunks.append(
                _silence(earlier, self.folder / f"blanc{self.rang}.wav")
            )
        piece = _synthesise(voice, text, self.folder / f"dit{self.rang}.wav")
        if piece is None:
            pytest.skip("synthèse impossible")
        self.chunks.append(piece)
        self.breathe()

    def breathe(self) -> None:
        """Pads the take so that the slice is worth transcribing."""
        import soundfile

        since = sum(
            float(soundfile.info(str(p)).duration)
            for p in self.chunks[self.last_turn:]
        )
        if since < self.USEFUL_SLICE:
            self.rang += 1
            self.chunks.append(_silence(
                self.USEFUL_SLICE - since,
                self.folder / f"souffle{self.rang}.wav",
            ))
        self.last_turn = len(self.chunks)

    def audio(self) -> Path:
        return _glue(self.chunks, self.folder / "reunion.wav")

    def duration(self) -> float:
        import soundfile

        return float(soundfile.info(str(self.audio())).duration)


@pytest.fixture(scope="module")
def transcriber():
    for out_of_reach in (voices_are_out_of_reach(2), the_called_name_is_out_of_reach()):
        if out_of_reach:
            pytest.skip(out_of_reach)
    tool = light_transcriber(Config())
    if tool is None:
        pytest.skip("aucun modèle de transcription installé")
    return tool


def _watcher(meeting: Reunion, the_assistant: AssistantSettings,
              transcriber, folder: Path) -> Watcher:
    return Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=folder / "propositions.jsonl",
        transcriber=transcriber,
        locate=lambda: Position(
            chunk=meeting.audio(), written=meeting.duration(), offset=0.0
        ),
        assistant_of=the_assistant,
        reread_participation=lambda: (True, False),
    )


def _the_assistant(brain: CerveauDeTest, voice: HautParleur) -> AssistantSettings:
    return AssistantSettings(
        name=NAME, brain=brain, voice=voice,
        manners=Manners(creux_minimal=0.0),
        context=lambda: "Réunion d'équipe sur la recette et la migration.",
    )


def _a_turn(watcher: Watcher, the_assistant: AssistantSettings,
             folder: Path) -> None:
    """One slice, then a wait for the answer: it is phrased in another thread."""
    where_in = watcher.locate()
    assert where_in is not None
    watcher.transcription_turn(where_in, folder)
    if the_assistant._job is not None:
        the_assistant._job.join(timeout=60)


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
        meeting = Reunion(tmp_path)
        meeting.say(ROOM_VOICE,
                     f"{NAME}, est-ce que tu peux faire des recherches sur Internet ?")
        brain = CerveauDeTest(answers=[
            "Je peux chercher, d'après la documentation de l'éditeur."
        ])
        voice = HautParleur()
        the_assistant = _the_assistant(brain, voice)
        watcher = _watcher(meeting, the_assistant, transcriber, tmp_path)

        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) == 1, voice.said_ones
        assert NAME not in voice.said_ones[0], "son nom ne doit jamais sortir"

        # The loudspeaker: what she said enters the room.
        meeting.say(ASSISTANT_VOICE, voice.said_ones[0])
        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) == 1, (
            "elle a répondu à sa propre voix : " + str(voice.said_ones)
        )

    def test_the_room_is_still_heard_after_it_has_spoken(
        self, transcriber, tmp_path
    ):
        """The other half: the guard must not make it deaf."""
        meeting = Reunion(tmp_path)
        meeting.say(ROOM_VOICE, f"{NAME}, où en est la recette ?")
        brain = CerveauDeTest(answers=[
            "La recette est décalée à jeudi.",
            "Il reste deux anomalies bloquantes.",
        ])
        voice = HautParleur()
        the_assistant = _the_assistant(brain, voice)
        watcher = _watcher(meeting, the_assistant, transcriber, tmp_path)

        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) == 1, voice.said_ones

        meeting.say(ASSISTANT_VOICE, voice.said_ones[0])
        meeting.say(ROOM_VOICE, f"Et les anomalies {NAME} ?")
        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) == 2, (
            "une nouvelle question de la salle doit obtenir une réponse : "
            + str(voice.said_ones)
        )

    def test_it_does_not_answer_when_nobody_calls_it(
        self, transcriber, tmp_path
    ):
        """An assistant that answers everything is as useless as a deaf one."""
        meeting = Reunion(tmp_path)
        meeting.say(ROOM_VOICE,
                     "On passe au point suivant, la recette est calée pour jeudi.")
        brain = CerveauDeTest()
        voice = HautParleur()
        the_assistant = _the_assistant(brain, voice)
        watcher = _watcher(meeting, the_assistant, transcriber, tmp_path)

        _a_turn(watcher, the_assistant, tmp_path)
        assert voice.said_ones == [], voice.said_ones
        assert brain.requests == [], "le modèle n'a même pas à être appelé"

    def test_it_does_not_cut_itself_off_while_still_speaking(
        self, transcriber, tmp_path
    ):
        """"Sometimes it starts speaking and it gets cut off."

        Two calls close together: the second must not kill the sentence under way.
        """
        meeting = Reunion(tmp_path)
        meeting.say(ROOM_VOICE, f"{NAME}, tu nous entends ?")
        brain = CerveauDeTest(answers=["Oui, je vous entends très bien."])
        voice = HautParleur()
        the_assistant = _the_assistant(brain, voice)
        watcher = _watcher(meeting, the_assistant, transcriber, tmp_path)

        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) == 1

        # She is still speaking when the next question arrives.
        voice.still_speaking = True
        meeting.say(ROOM_VOICE,
                     f"{NAME}, et où en est la migration en Symfony sept ?")
        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) == 1, "rien de neuf n'a été prononcé"
        assert voice.cuts >= 1, "le refus doit avoir eu lieu"
        assert voice.still_speaking, "la phrase en cours n'a pas été coupée"

    def test_the_transcriber_loop_does_not_multiply_it(
        self, transcriber, tmp_path
    ):
        """The same question repeated gets one answer only."""
        meeting = Reunion(tmp_path)
        for _ in range(3):
            meeting.say(ROOM_VOICE, f"{NAME}, tu peux nous rappeler la date ?",
                         earlier=0.15)
        brain = CerveauDeTest(answers=["C'est jeudi."])
        voice = HautParleur()
        the_assistant = _the_assistant(brain, voice)
        watcher = _watcher(meeting, the_assistant, transcriber, tmp_path)

        _a_turn(watcher, the_assistant, tmp_path)
        assert len(voice.said_ones) <= 1, voice.said_ones

    def test_a_participant_restating_their_idea_is_heard(
        self, transcriber, tmp_path
    ):
        """The risk of the guard by words: taking a human for her."""
        from greffier.domain.participation import own_words

        the_assistant = _the_assistant(CerveauDeTest(), HautParleur())
        the_assistant.its_own_words.append((0.0, own_words("La recette est décalée à jeudi.")))
        from greffier.domain.models import Span, Utterance

        human = Utterance(
            span=Span(300.0, 306.0),
            text="je propose plutôt de caler la recette mardi avec Pascal",
        )
        assert not the_assistant._is_his_own(human, 310.0)
