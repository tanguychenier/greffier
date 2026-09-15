#!/usr/bin/env python3
"""Measures what the chain is worth on the real recordings of `docs/corpus.md`.

Three figures per recording, none of them adjustable by hand:

- **word error rate**, against a reference written by people, once both sides
  are read the same way (lower case, no punctuation, no fillers);
- **rare terms found**, the words the reference uses once and that a model
  is tempted to replace with a commoner one: it is where "backlog" became
  "bâcle";
- **attribution**, the share of sentences whose voice was given to the right
  person, once every voice is matched to the person it mostly carries. The
  rest splits between *wrong* and *no opinion*, the sentence left without a
  voice, because the two are not the same failure: a wrong name in the minutes
  is worse than a blank.

Where the reference carries timings (SUMM-RE), the truth of a sentence is the
speaker active under it. Where it only carries the words in order (the
minutes of the Assemblée), the sentence is aligned to the reference text and
takes the speaker of the words it lands on; an edited text forbids a raw
error rate, so that figure is printed but marked as such.

    python3 tools/measure_corpus.py                # every recording of the corpus folder
    python3 tools/measure_corpus.py --only summre  # those whose name contains it
    python3 tools/measure_corpus.py --again        # transcribe again instead of reading the cache

The chain runs with the installed models and the user's settings, but writes
into a folder of its own: measuring must not add a meeting to the list.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greffier.locations import data_folder  # noqa: E402

#: Fillers the reference writes down and a transcriber drops: neither side is
#: wrong about them, so neither side is counted on them.
FILLERS = frozenset({"euh", "hum", "mh", "mhm", "hm", "mmh", "heu"})

#: A rare term: used once in the reference, long enough to be a word the model
#: had to know rather than guess.
RARE_LENGTH = 7

#: Below this, a sentence has too few words matched in the minutes to say who
#: spoke it.
MATCHED_WORDS_MINIMUM = 3

#: A voice that spoke less than this is a scrap, not an attendee: the same
#: floor as the product's `significant_voices`, so that the count printed here
#: is the count the minutes would announce.
ATTENDEE_SECONDS = 10.0

#: Forty minutes of audio against the minutes of two hours and a half: the
#: alignment lands a few common words far beyond the part that was heard.
#: The heard part is where matches are dense; it ends once this many
#: consecutive slices fall under a quarter of the typical density.
SLICE = 100
QUIET_SLICES = 3

_APOSTROPHE = re.compile(r"([a-zàâçéèêëîïôûùüÿœ])['’]\s+")
_NOT_A_LETTER = re.compile(r"[^a-z0-9àâçéèêëîïôûùüÿœæ' ]+")


def normalise(text: str) -> list[str]:
    """The words of a text, read the way both sides can be compared."""
    lowered = text.lower().replace("_", " ").replace("’", "'")
    lowered = _APOSTROPHE.sub(r"\1'", lowered)
    lowered = _NOT_A_LETTER.sub(" ", lowered)
    return [word for word in lowered.split() if word not in FILLERS]


def word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    from rapidfuzz.distance import Levenshtein

    if not reference:
        return 0.0
    return Levenshtein.distance(reference, hypothesis) / len(reference)


def rare_terms(reference: list[str]) -> set[str]:
    counts = Counter(reference)
    return {word for word, seen in counts.items() if seen == 1 and len(word) >= RARE_LENGTH}


def terms_found(terms: set[str], hypothesis: list[str]) -> tuple[int, int]:
    heard = set(hypothesis)
    return sum(1 for term in terms if term in heard), len(terms)


@dataclass(frozen=True)
class Sentence:
    start: float
    end: float
    text: str
    voice: str | None


Turn = dict[str, Any]


def truth_by_time(sentences: list[Sentence], turns: list[Turn]) -> list[str | None]:
    """Who the reference says was speaking under each sentence, or None."""
    truths: list[str | None] = []
    for sentence in sentences:
        under: dict[str, float] = defaultdict(float)
        for turn in turns:
            begins = max(sentence.start, float(turn["start"]))
            covered = min(sentence.end, float(turn["end"])) - begins
            if covered > 0:
                under[str(turn["speaker"])] += covered
        if not under:
            truths.append(None)
            continue
        speaker, covered = max(under.items(), key=lambda item: item[1])
        truths.append(speaker if covered > sum(under.values()) / 2 else None)
    return truths


@dataclass(frozen=True)
class TextAlignment:
    """What aligning the sentences on an edited text yields."""

    truths: list[str | None]
    covered: list[str]
    """The reference words between the first and the last the sentences land on.

    Forty minutes of audio against the minutes of two hours and a half: the
    error rate only means something on the part of the text that was heard.
    """


def truth_by_text(sentences: list[Sentence], turns: list[Turn]) -> TextAlignment:
    """Who the minutes give the words of each sentence to, or None."""
    from rapidfuzz.distance import Levenshtein

    reference_words: list[str] = []
    owners: list[str] = []
    for turn in turns:
        words = normalise(str(turn["text"]))
        reference_words.extend(words)
        owners.extend([str(turn["speaker"])] * len(words))

    hypothesis_words: list[str] = []
    sentence_of_word: list[int] = []
    for index, sentence in enumerate(sentences):
        words = normalise(sentence.text)
        hypothesis_words.extend(words)
        sentence_of_word.extend([index] * len(words))

    matched: dict[int, Counter[str]] = defaultdict(Counter)
    positions: list[int] = []
    for opcode in Levenshtein.opcodes(hypothesis_words, reference_words):
        if opcode.tag != "equal":
            continue
        positions.extend(range(opcode.dest_start, opcode.dest_end))
        for offset in range(opcode.src_end - opcode.src_start):
            which = sentence_of_word[opcode.src_start + offset]
            matched[which][owners[opcode.dest_start + offset]] += 1
    first, last = covered_region(positions, len(reference_words))

    truths: list[str | None] = []
    for index in range(len(sentences)):
        seen = matched.get(index)
        if not seen or sum(seen.values()) < MATCHED_WORDS_MINIMUM:
            truths.append(None)
            continue
        truths.append(seen.most_common(1)[0][0])
    return TextAlignment(truths, reference_words[first:last])


def covered_region(positions: list[int], total: int) -> tuple[int, int]:
    """Where the matches are dense: the part of the reference that was heard."""
    if not positions:
        return (0, 0)
    per_slice = Counter(position // SLICE for position in positions)
    slices = range(total // SLICE + 1)
    typical = sorted(per_slice.values())[len(per_slice) // 2]
    dense = [per_slice.get(index, 0) >= typical / 4 for index in slices]
    start = dense.index(True)
    end, quiet = start, 0
    for index in range(start, len(dense)):
        if dense[index]:
            end, quiet = index, 0
        else:
            quiet += 1
            if quiet >= QUIET_SLICES:
                break
    return (start * SLICE, min(total, (end + 1) * SLICE))


@dataclass(frozen=True)
class Attribution:
    judged: int
    right: int
    wrong: int
    no_opinion: int
    voices: int
    scraps: int
    people: int

    @property
    def accuracy(self) -> float:
        return self.right / self.judged if self.judged else 0.0


def attribution(sentences: list[Sentence], truths: list[str | None]) -> Attribution:
    """Right, wrong and no opinion, once each voice is the person it mostly carries."""
    carried: dict[str, Counter[str]] = defaultdict(Counter)
    for sentence, truth in zip(sentences, truths, strict=True):
        if truth is not None and sentence.voice is not None:
            carried[sentence.voice][truth] += 1
    person_of = {voice: seen.most_common(1)[0][0] for voice, seen in carried.items()}

    right = wrong = no_opinion = judged = 0
    for sentence, truth in zip(sentences, truths, strict=True):
        if truth is None:
            continue
        judged += 1
        if sentence.voice is None or sentence.voice not in person_of:
            no_opinion += 1
        elif person_of[sentence.voice] == truth:
            right += 1
        else:
            wrong += 1
    spoken: dict[str, float] = defaultdict(float)
    for sentence in sentences:
        if sentence.voice is not None:
            spoken[sentence.voice] += sentence.end - sentence.start
    attendees = sum(1 for seconds in spoken.values() if seconds >= ATTENDEE_SECONDS)
    return Attribution(
        judged=judged,
        right=right,
        wrong=wrong,
        no_opinion=no_opinion,
        voices=attendees,
        scraps=len(spoken) - attendees,
        people=len({truth for truth in truths if truth is not None}),
    )


def run_the_chain(audio: Path) -> list[Sentence]:
    """The sentences the installed chain gives for this recording, voices attached."""
    from greffier.adapters.configuration import Config
    from greffier.wiring import wire_up

    with tempfile.TemporaryDirectory() as folder:
        config = Config(paths={"donnees": folder, "modeles": str(data_folder() / "modeles")})
        config.minutes.engine = "aucun"
        chain = wire_up(config)
        chain.writer = None
        chain.sender = None
        outcome = chain.run_chain(audio, send=False)
    return [
        Sentence(u.span.start, u.span.end, u.text, u.voice)
        for u in sorted(outcome.utterances, key=lambda u: u.span.start)
    ]


def sentences_of(audio: Path, again: bool) -> list[Sentence]:
    cache = audio.with_suffix(".outcome.json")
    if cache.exists() and not again:
        return [Sentence(**entry) for entry in json.loads(cache.read_text(encoding="utf-8"))]
    sentences = run_the_chain(audio)
    cache.write_text(
        json.dumps([vars(s) for s in sentences], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return sentences


def measure(audio: Path, again: bool) -> dict[str, object]:
    reference = json.loads(audio.with_suffix(".reference.json").read_text(encoding="utf-8"))
    turns = reference["turns"]
    timed = "start" in turns[0]
    sentences = sentences_of(audio, again)

    hypothesis_words = [word for sentence in sentences for word in normalise(sentence.text)]
    if timed:
        in_order = sorted(turns, key=lambda t: float(t["start"]))
        reference_words = [word for turn in in_order for word in normalise(str(turn["text"]))]
        truths = truth_by_time(sentences, turns)
    else:
        aligned = truth_by_text(sentences, turns)
        reference_words, truths = aligned.covered, aligned.truths
    terms = rare_terms(reference_words)
    found, wanted = terms_found(terms, hypothesis_words)
    result = attribution(sentences, truths)
    return {
        "recording": audio.stem,
        "reference_timed": timed,
        "reference_words": len(reference_words),
        "hypothesis_words": len(hypothesis_words),
        "word_error_rate": word_error_rate(reference_words, hypothesis_words),
        "rare_terms_found": found,
        "rare_terms": wanted,
        "sentences": len(sentences),
        "sentences_judged": result.judged,
        "attribution_right": result.right,
        "attribution_wrong": result.wrong,
        "attribution_no_opinion": result.no_opinion,
        "voices": result.voices,
        "scraps": result.scraps,
        "people": result.people,
    }


def print_row(row: dict[str, object]) -> None:
    judged = int(str(row["sentences_judged"])) or 1
    wer = float(str(row["word_error_rate"])) * 100
    note = "" if row["reference_timed"] else " (texte relu)"
    right, wrong, blank = (
        100 * int(str(row[key])) / judged
        for key in ("attribution_right", "attribution_wrong", "attribution_no_opinion")
    )
    print(
        f"{row['recording']:<24} "
        f"erreur de mots {wer:5.1f} %{note:<14} "
        f"termes rares {row['rare_terms_found']:>3}/{row['rare_terms']:<3} "
        f"justesse {right:5.1f} % faux {wrong:4.1f} % sans avis {blank:4.1f} % "
        f"voix {row['voices']}/{row['people']} (+{row['scraps']} miettes)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=data_folder() / "corpus")
    parser.add_argument("--only", default="")
    parser.add_argument("--again", action="store_true")
    options = parser.parse_args()

    recordings = sorted(
        audio
        for audio in options.corpus.glob("*.wav")
        if options.only in audio.stem and audio.with_suffix(".reference.json").exists()
    )
    if not recordings:
        print(f"Aucun enregistrement avec référence dans {options.corpus}")
        return 1
    for audio in recordings:
        row = measure(audio, options.again)
        audio.with_suffix(".measure.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print_row(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
