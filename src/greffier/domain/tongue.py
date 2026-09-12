"""The language the tool speaks to the person using it.

Not the language of the meeting -- that is `transcription.langue`, and a French
team can perfectly well hold a meeting in English. This is the language of the
window, of the installer's messages, of what the tool says about itself.

Two rules, and they are all there is to it. The machine's language decides,
because nobody should have to choose what their system already knows; and a
language the tool does not speak falls back to English rather than to French,
because a French window is unreadable to somebody who did not ask for it,
whereas English at least is the language this trade already speaks.

Pure: the decision, and what a catalogue of wordings does when a key is missing
from it. Where the catalogues live, and how a machine is asked for its language,
belong to the adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What the tool is translated into today. A new language is a new file in the
#: catalogue and a line here -- that is the whole ceremony.
SPOKEN: tuple[str, ...] = ("fr", "en")

#: Where an unknown language lands. English rather than French: the tool is
#: French-speaking by origin, not by right.
FALLBACK = "en"


def choose(asked: str, spoken: tuple[str, ...] = SPOKEN) -> str:
    """The language to speak, from what a machine or a setting says.

    Takes anything a system hands out -- `fr_FR.UTF-8`, `fr-CA`, `FR`, `C`,
    an empty string -- and answers a language this tool speaks. A region is
    dropped: Québécois and Belgian French read the same window.
    """
    code = (asked or "").strip().replace("-", "_").split(".")[0].split("_")[0].lower()
    if code in spoken:
        return code
    return FALLBACK if FALLBACK in spoken else (spoken[0] if spoken else FALLBACK)


@dataclass(frozen=True, slots=True)
class Wording:
    """What the tool says, in one language, with English behind it.

    A key missing from a translation falls back to the default rather than
    showing the key itself: a half-translated language must read as a language,
    not as a bug report. What is missing is knowable -- `missing()` says it --
    so that it can be translated rather than discovered by a reader.
    """

    language: str
    says: dict[str, str] = field(default_factory=dict)
    default: dict[str, str] = field(default_factory=dict)

    def say(self, key: str, **parts: object) -> str:
        """The sentence for this key, filled in, or the key when it is nowhere."""
        phrase = self.says.get(key) or self.default.get(key) or key
        if not parts:
            return phrase
        try:
            return phrase.format(**parts)
        except (KeyError, IndexError):
            # A wording whose holes do not match what is handed to it is a
            # translation mistake, and showing the raw sentence is more useful
            # to whoever must fix it than an exception in the middle of a window.
            return phrase

    def missing(self) -> tuple[str, ...]:
        """The keys this language has not translated yet."""
        return tuple(sorted(set(self.default) - set(self.says)))

    @property
    def complete(self) -> bool:
        return not self.missing()


@dataclass(frozen=True, slots=True)
class Voice:
    """The assistant's voice for one language, as a sherpa-onnx release names it.

    Data and not code: the installer reads this table by loading this file
    literally, the way it already reads the list of languages, so that a voice
    is declared once rather than in two places that drift apart.
    """

    language: str
    archive: str
    speakers: int = 1
    weight_mb: int = 80


#: One voice per language the tool speaks. Adding a language means adding its
#: voice here, and nothing else: what downloads it reads this table.
VOICES: dict[str, Voice] = {
    "fr": Voice("fr", "vits-piper-fr_FR-upmc-medium", speakers=2, weight_mb=80),
    "en": Voice("en", "vits-piper-en_US-amy-medium", speakers=1, weight_mb=65),
}


def voice_for(language: str) -> Voice | None:
    """The voice to install for this language, or None where there is none yet.

    None is an honest answer: the assistant then falls back on the system voice,
    which speaks badly rather than not at all.
    """
    return VOICES.get(choose(language))
