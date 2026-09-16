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
    python3 tools/measure_bank.py --replay     # the live thread again, without the transcriber

Two figures per person and overall: the share of their sentences carried by
a voice the bank named right, and the number of voices the tool split them
into. Everything lives in `corpus/bank/` under the data folder; nothing
touches the machine's own bank.

`--replay` feeds the live thread the words it showed last time
(`tools/replay_follower.py`) and measures the attribution alone, in the time the
voiceprints take: it is how a change to who-said-what is judged without
the card.
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
    config: Any, audio: Path, replay_from: Path | None = None
) -> tuple[list[Sentence], dict[str, str | None], dict[str, str | None]]:
    """The second meeting as the window would have shown it, bank in hand.

    Two readings of the names. The name each sentence carried at the
    moment it was shown, read from the log the thread writes, since a name
    the bank changes its mind about later was on screen meanwhile. And the
    name each voice ends up with, which is what the minutes will carry.

    Given a log to replay from, the transcriber stays closed: the follower
    gets the sentences of that log, slice by slice, and the thread it
    builds lands in a log of its own.
    """
    import soundfile as sf

    from greffier.application.follow import Position, files
    from greffier.application.watch import Watcher
    from greffier.domain.instructions import WatchRules
    from greffier.wiring import _audio_recorder, follower, light_transcriber

    duration = sf.info(str(audio)).duration
    the_follower = follower(config, audio.stem)
    if replay_from is not None:
        from replay_follower import replay_through

        the_follower.log, the_follower.requests = files(
            config.paths.live, f"{audio.stem}.replayed"
        )
        the_follower.log.unlink(missing_ok=True)
        replay_through(the_follower, replay_from, audio, config.live.period)
    else:
        # A fresh thread, or the replay would read two meetings in one log.
        the_follower.log.unlink(missing_ok=True)
        the_follower.requests.unlink(missing_ok=True)
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
    at_the_end = {voice: thread.voice[voice].name for voice in thread.voice}
    return sentences, at_the_moment(the_follower.log), at_the_end


def at_the_moment(log: Path) -> dict[str, str | None]:
    """The name each sentence carried when it was shown, keyed « #number ».

    The turn lines of the log carry the name at the time of writing. Judged
    with `by_number`, which gives each sentence a voice of its own, the same
    verdict counts names that belong to a moment rather than to a voice.
    """
    from greffier.application.follow import KIND_TURN, read_from

    lines, _ = read_from(log, 0)
    return {
        f"#{line['numero']}": line.get("nom")
        for line in lines if line.get("genre") == KIND_TURN
    }


def by_number(sentences: list[Sentence]) -> list[Sentence]:
    """The same sentences, each carrying its number as its voice."""
    return [
        Sentence(s.start, s.end, s.text, f"#{number}")
        for number, s in enumerate(sentences, start=1)
    ]


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
    parser.add_argument("--replay", action="store_true",
                        help="the live thread on the words of its last run, no transcriber")
    parser.add_argument("--device", default=None,
                        help="cpu or cuda for the models; the configuration's otherwise")
    parser.add_argument("--material", type=float, default=None,
                        help="seconds of speech the bank waits for before naming a voice "
                             "(the product's MATERIAL_TO_RECOGNISE otherwise)")
    options = parser.parse_args()
    if options.material is not None:
        from greffier.domain import live

        live.MATERIAL_TO_RECOGNISE = options.material

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
    if options.device:
        config.hardware.device = options.device
    last_live = config.paths.live / f"{SECOND}.jsonl"
    if options.replay and not last_live.exists():
        print(f"{last_live} missing: run once without --replay first")
        return 1

    if options.replay:
        named = {}
        print(f"{FIRST}: bank kept from the last run, at {config.paths.voice_bank}")
    else:
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
        sentences, shown, at_the_end = through_the_live_thread(
            config, second, last_live if options.replay else None
        )
        shown_verdict = judged(by_number(sentences), shown, _turns(second))
        end_verdict = judged(sentences, at_the_end, _turns(second))
        _print(f"{SECOND}, live thread, the names as they were shown", shown_verdict)
        _print(f"{SECOND}, live thread, the names the voices end up with", end_verdict)
        result["live_shown"] = shown_verdict
        result["live_end"] = end_verdict
    kept = "bank.replayed.json" if options.replay else "bank.json"
    (options.corpus / f"{SECOND}.{kept}").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
