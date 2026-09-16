#!/usr/bin/env python3
"""Measures whether a person named once is recognised at the next meeting.

The question from use: does the tool keep somebody's voice, so that a person
named on Monday is named by the tool on Thursday, whatever their tone that
day? SUMM-RE has the same four people across a series: 032a is their
reporting meeting, 032b their decision meeting. The four voices of 032a are
named after the reference, through the product's own gesture (`Naming`, the
one behind « greffier nommer »), which files their voiceprints in the bank.
032b then goes through the chain with that bank, and through the live thread
with it, and each sentence the reference attributes is checked: the tool
named the right person, the wrong one, or nobody.

    python3 tools/measure_bank.py
    python3 tools/measure_bank.py --again      # run the chain again rather than reuse

Two figures per person and overall: the share of their sentences carried by
a voice the bank named right, and the number of voices the tool split them
into. Everything lives in `corpus/bank/` under the data folder; nothing
touches the machine's own bank.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from measure_corpus import ATTENDEE_SECONDS, Sentence, truth_by_time  # noqa: E402

from greffier.locations import data_folder  # noqa: E402

FIRST = "summre-032a_EARH"
SECOND = "summre-032b_EADH"

#: The reference knows the four people by number; the bank wants first names.
NAMES = {"084": "Alice", "085": "Bruno", "086": "Chloé", "087": "Diane"}


def _config(data: Path) -> Any:
    from greffier.adapters.configuration import Config

    config = Config(paths={"donnees": str(data), "modeles": str(data_folder() / "modeles")})
    config.minutes.engine = "aucun"
    return config


def _turns(audio: Path) -> list[dict[str, Any]]:
    reference = json.loads(audio.with_suffix(".reference.json").read_text(encoding="utf-8"))
    return list(reference["turns"])


def _sentences(outcome: Any) -> list[Sentence]:
    return [
        Sentence(u.span.start, u.span.end, u.text, u.voice)
        for u in sorted(outcome.utterances, key=lambda u: u.span.start)
    ]


def run_the_chain(config: Any, audio: Path, again: bool) -> Any:
    """The chain on one recording, its outcome kept next to the data."""
    from greffier.wiring import wire_up

    cache = config.paths.data / f"{audio.stem}.outcome.pickle"
    if cache.exists() and not again:
        import pickle

        return pickle.loads(cache.read_bytes())
    chain = wire_up(config)
    chain.writer = None
    chain.sender = None
    outcome = chain.run_chain(audio, send=False)
    import pickle

    cache.write_bytes(pickle.dumps(outcome))
    return outcome


def person_of_each_voice(sentences: list[Sentence], turns: list[dict[str, Any]]) -> dict[str, str]:
    """The reference person each voice mostly carries, for the voices that matter."""
    carried: dict[str, Counter[str]] = defaultdict(Counter)
    spoken: dict[str, float] = defaultdict(float)
    for sentence, truth in zip(sentences, truth_by_time(sentences, turns), strict=True):
        if sentence.voice is None:
            continue
        spoken[sentence.voice] += sentence.end - sentence.start
        if truth is not None:
            carried[sentence.voice][truth] += 1
    return {
        voice: seen.most_common(1)[0][0]
        for voice, seen in carried.items()
        if spoken[voice] >= ATTENDEE_SECONDS
    }


def name_the_first_meeting(config: Any, audio: Path, outcome: Any) -> dict[str, str]:
    """Names each voice of the first meeting as the product would, from the reference."""
    from greffier.wiring import naming

    who = person_of_each_voice(_sentences(outcome), _turns(audio))
    gesture = naming(config)
    named: dict[str, str] = {}
    for voice, person in who.items():
        gesture.name_voice(audio.stem, voice, NAMES[person])
        named[voice] = NAMES[person]
    return named


def judged(sentences: list[Sentence], names: dict[str, str | None],
           turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Right, wrong and nobody, per person and overall, on the reference's sentences."""
    per_person: dict[str, Counter[str]] = defaultdict(Counter)
    voices_of: dict[str, set[str]] = defaultdict(set)
    for sentence, truth in zip(sentences, truth_by_time(sentences, turns), strict=True):
        if truth is None:
            continue
        person = NAMES[truth]
        given = names.get(sentence.voice) if sentence.voice else None
        if sentence.voice:
            voices_of[person].add(sentence.voice)
        if given is None:
            per_person[person]["nobody"] += 1
        elif given == person:
            per_person[person]["right"] += 1
        else:
            per_person[person]["wrong"] += 1
    overall: Counter[str] = Counter()
    for counts in per_person.values():
        overall.update(counts)
    return {
        "per_person": {
            person: {**counts, "voices": len(voices_of[person])}
            for person, counts in sorted(per_person.items())
        },
        "right": overall["right"], "wrong": overall["wrong"], "nobody": overall["nobody"],
    }


def through_the_live_thread(
    config: Any, audio: Path
) -> tuple[list[Sentence], dict[str, str | None], dict[str, str | None]]:
    """The second meeting as the window would have shown it, bank in hand.

    Two readings of the names: the ones the thread is sure of (recognised
    with a margin, or given by a person), and every name it shows, the
    probable ones included, which the window paints in the colour of doubt.
    """
    import soundfile as sf

    from greffier.application.follow import Position
    from greffier.application.watch import Watcher
    from greffier.domain.instructions import WatchRules
    from greffier.wiring import _audio_recorder, follower, light_transcriber

    duration = sf.info(str(audio)).duration
    the_follower = follower(config, audio.stem)
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=config.paths.propositions / f"{audio.stem}.jsonl",
        transcriber=light_transcriber(config),
        follower=the_follower,
        preparer=_audio_recorder(config),
        language="fr",
        slice_period=config.live.period,
    )
    with tempfile.TemporaryDirectory() as job:
        written = config.live.period
        while written <= duration + config.live.period:
            where = Position(chunk=audio, written=min(written, duration), offset=0.0)
            watcher.transcription_turn(where, Path(job), let_speak=False)
            written += config.live.period
    thread = the_follower.thread
    sentences = [Sentence(t.span.start, t.span.end, t.text, t.voice) for t in thread.turns]
    shown = {voice: thread.voice[voice].name for voice in thread.voice}
    from greffier.domain.live import Certainty

    guesses = {Certainty.UNKNOWN, Certainty.PROBABLE}
    sure = {
        voice: (known.name if known.certainty not in guesses else None)
        for voice, known in thread.voice.items()
    }
    return sentences, sure, shown


def _print(title: str, verdict: dict[str, Any]) -> None:
    total = verdict["right"] + verdict["wrong"] + verdict["nobody"]
    print(f"{title}: {verdict['right']}/{total} sentences named right, "
          f"{verdict['wrong']} wrong, {verdict['nobody']} left to nobody")
    for person, counts in verdict["per_person"].items():
        seen = counts.get("right", 0) + counts.get("wrong", 0) + counts.get("nobody", 0)
        print(f"  {person:<7} right {counts.get('right', 0):>3}/{seen:<3}  "
              f"wrong {counts.get('wrong', 0):>3}  nobody {counts.get('nobody', 0):>3}  "
              f"voices {counts['voices']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, default=data_folder() / "corpus")
    parser.add_argument("--again", action="store_true", help="run the chain again")
    parser.add_argument("--skip-live", action="store_true", help="the chain only")
    options = parser.parse_args()

    first, second = options.corpus / f"{FIRST}.wav", options.corpus / f"{SECOND}.wav"
    for audio in (first, second):
        if not audio.exists() or not audio.with_suffix(".reference.json").exists():
            print(f"{audio.name} missing: python3 tools/fetch_corpus.py summre")
            return 1
    data = options.corpus / "bank"
    if options.again and data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True, exist_ok=True)
    config = _config(data)

    first_outcome = run_the_chain(config, first, options.again)
    named = name_the_first_meeting(config, first, first_outcome)
    print(f"{FIRST}: {len(named)} voices named ({', '.join(sorted(set(named.values())))}), "
          f"bank at {config.paths.voice_bank}")

    second_outcome = run_the_chain(config, second, options.again)
    chain_verdict = judged(_sentences(second_outcome), dict(second_outcome.names), _turns(second))
    _print(f"{SECOND}, after the meeting", chain_verdict)
    result: dict[str, Any] = {"first": FIRST, "second": SECOND, "named": named,
                              "chain": chain_verdict}
    if not options.skip_live:
        sentences, sure, shown = through_the_live_thread(config, second)
        sure_verdict = judged(sentences, sure, _turns(second))
        shown_verdict = judged(sentences, shown, _turns(second))
        _print(f"{SECOND}, live thread, the names it is sure of", sure_verdict)
        _print(f"{SECOND}, live thread, every name it shows", shown_verdict)
        result["live_sure"] = sure_verdict
        result["live_shown"] = shown_verdict
    (options.corpus / f"{SECOND}.bank.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
