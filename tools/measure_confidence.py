#!/usr/bin/env python3
"""Measures what the confidence the model returns is worth.

Whisper gives an `avg_logprob` per segment; its exponential is the mean
probability per token. What remains to know is whether that figure really
separates right turns from wrong ones, and where to put the line. Nobody had
measured it, and a threshold not measured is a threshold made up.

    .venv/bin/python tools/measure_confidence.py meeting.wav reference.txt

`reference.txt` carries the expected text, one line per speaker turn, in
order. The script transcribes, aligns each turn on its reference, and sorts
the turns by confidence, saying for each step how many words are wrong above
and below.

With no argument, it makes a meeting itself with `tools/make_meeting.py`,
hence with the speech synthesis installed on the machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _bare(text: str) -> list[str]:
    """The words alone: no punctuation, no capitals, no hyphens.

    The model chooses its punctuation and its cuts; "Jacques. Je vous" against
    "Jacques, je vous" is the same sentence heard the same, and counting it as
    two wrong words drowns the real errors.
    """
    import re
    import unicodedata

    stripped = unicodedata.normalize("NFD", text.lower().replace("-", ""))
    unaccented = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9']+", unaccented)


def _word_errors(said: str, expected: str) -> tuple[int, int]:
    """Wrong words and expected words, by the edit distance on the words."""
    from rapidfuzz.distance import Levenshtein

    wanted = _bare(expected)
    return Levenshtein.distance(_bare(said), wanted), len(wanted)


def _transcribe(audio: Path, language: str = "fr") -> list[object]:
    from greffier.adapters.configuration import Config
    from greffier.wiring import _transcriber

    config = Config()
    engine = _transcriber(config)
    print(f"  transcribing {audio.name}…", flush=True)
    return list(engine.transcribe(audio, language, ""))


def _aligned(utterances: list[object], reference: list[str]) -> list[tuple[object, str]]:
    """Each turn with the closest reference line, in order.

    The model's cuts do not follow the reference's: two sentences may fall in
    one segment. So the reference is walked as we go, which is enough for a
    test set whose order is known.
    """
    out = []
    left = list(reference)
    for utterance in utterances:
        if not left:
            break
        out.append((utterance, left.pop(0)))
    return out


def _say_what_differs(pairs: list[tuple[object, str]]) -> None:
    """The words that are not the right ones, to judge what is measured.

    An error rate without the words behind it cannot be read back: the first
    version of this script counted "pré-production" against "préproduction"
    as two wrong words, and the gap measured was its own, not the model's.
    """
    from rapidfuzz.distance import Levenshtein

    for utterance, expected in pairs:
        said, wanted = _bare(getattr(utterance, "text", "")), _bare(expected)
        gaps = [
            (edit, said[i] if i < len(said) else "",
             wanted[j] if j < len(wanted) else "")
            for edit, i, _, j, _ in Levenshtein.opcodes(said, wanted)
            if edit != "equal"
        ]
        if gaps:
            print("    gaps: " + ", ".join(
                f"« {heard or '∅'} » instead of « {expected_word or '∅'} »"
                for _, heard, expected_word in gaps
            ))


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    audio = Path(sys.argv[1])
    reference = [
        line.strip() for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not audio.exists():
        print(f"✗ {audio} not found")
        return 1

    pairs = _aligned(_transcribe(audio), reference)
    if not pairs:
        print("✗ nothing was transcribed")
        return 1

    measures = []
    for utterance, expected in pairs:
        wrong, total = _word_errors(getattr(utterance, "text", ""), expected)
        measures.append((getattr(utterance, "confidence", None), wrong, total,
                         getattr(utterance, "text", "")))

    judged = [m for m in measures if m[0] is not None]
    if not judged:
        print("✗ the engine returned no confidence: nothing to measure")
        return 1

    print(f"\n{len(judged)} turn(s) judged out of {len(measures)}\n")
    _say_what_differs(pairs)
    print("  confidence   wrong / expected words   text")
    for confidence, wrong, total, text in sorted(judged, key=lambda m: m[0] or 0.0):
        mark = "✗" if wrong else " "
        print(f"  {confidence:>10.2f}   {mark} {wrong:>3} / {total:<3}"
              f"            {text[:56]}")

    right = [m[0] for m in judged if m[1] == 0]
    faulty = [m[0] for m in judged if m[1] > 0]
    print()
    if right:
        print(f"  right turns     : {len(right)}, confidence from "
              f"{min(right):.2f} to {max(right):.2f}")
    if faulty:
        print(f"  faulty turns    : {len(faulty)}, confidence from "
              f"{min(faulty):.2f} to {max(faulty):.2f}")
    if right and faulty and max(faulty) < min(right):
        limit = (max(faulty) + min(right)) / 2
        print(f"\n  The two do not overlap: the line falls at {limit:.2f}")
    elif right and faulty:
        print("\n  The two overlap: no threshold separates them cleanly on this set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
