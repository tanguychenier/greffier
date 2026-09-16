#!/usr/bin/env python3
"""Times the assistant, from the end of a question to its first word.

The whole chain that runs in a meeting, in this process and in real time: the
listening pass that spots her name, the model that phrases the answer, the
voice that renders it. Only the loudspeaker is replaced, by a clock. The
meeting is a synthesised dialogue that asks her three questions and leaves
her room to answer, so the same file measures every change to the chain.

    python3 tools/measure_assistant.py
    python3 tools/measure_assistant.py --model opus --runs 2

For each question: when her name was spotted, when the answer came back, when
the first sentence was ready to play, all counted from the end of the
question. What the room feels is the last figure.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from make_meeting import PAUSE  # noqa: E402

#: Room to answer after each question: a real table waits, and a bench that
#: put the next line straight after would measure the overlap, not the delay.
ROOM = "12"

#: What a room takes to settle before the first word: the models open then.
WARM_UP_S = 15.0

DIALOGUE: list[tuple[str | None, str]] = [
    ("A", "Bonjour à tous, moi c'est Jacques, on fait le point sur la recette, "
          "qui nous occupe depuis le début de la semaine."),
    ("B", "Merci Jacques. Il reste exactement deux anomalies bloquantes sur la "
          "facturation, corrigées hier soir mais pas encore validées."),
    ("A", "Lucie, combien d'anomalies bloquantes restent à valider ?"),
    (PAUSE, ROOM),
    ("B", "On décale donc la recette à jeudi prochain, et nous préviendrons les "
          "utilisateurs mercredi en fin de journée."),
    ("A", "Lucie, à quel jour est décalée la recette ?"),
    (PAUSE, ROOM),
    ("A", "Lucie, c'est quoi une préproduction, en une phrase ?"),
    (PAUSE, ROOM),
]


class Clock:
    """What the bench records, in seconds since the replay started."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.events: list[tuple[str, float, str]] = []

    def now(self) -> float:
        return time.monotonic() - self.started

    def mark(self, what: str, detail: str = "") -> None:
        self.events.append((what, self.now(), detail))


def _meeting(folder: Path) -> tuple[Path, list[dict[str, Any]]]:
    from make_meeting import make

    audio = make(folder / "reunion.wav", dialogue=DIALOGUE)
    timeline = json.loads(audio.with_suffix(".timeline.json").read_text(encoding="utf-8"))
    return audio, timeline


def _instrumented(lui: Any, clock: Clock) -> None:
    """Hooks on the three steps, the loudspeaker replaced by the clock."""
    brain = lui.cerveau
    write_up = brain.write_up

    def timed_write_up(text: str) -> str:
        clock.mark("asked")
        answer = write_up(text)
        clock.mark("answered", answer)
        return answer

    brain.write_up = timed_write_up
    answer_aside = lui.answer_aside

    def timed_answer_aside(opening: Any, now: float) -> None:
        clock.mark("spotted", opening.remark)
        answer_aside(opening, now)

    lui.answer_aside = timed_answer_aside
    voice = lui.voice
    if voice is not None and hasattr(voice, "_play"):
        def silent_play(file: Path) -> bool:
            clock.mark("ready", file.name)
            return True

        voice._play = silent_play


def replay(audio: Path, config: Any, model: str, brain: Any | None = None) -> Clock:
    """The meeting replayed through the chain; `brain` doubles the model when given."""
    import soundfile as sf

    from greffier.application.follow import Position
    from greffier.application.watch import Watcher
    from greffier.cli import _live_material, _warm_up_aside
    from greffier.domain.instructions import WatchRules
    from greffier.wiring import assistant_of, follower, light_transcriber, somebody_speaking

    if model:
        config.assistant.model = model
    identifier = "banc-assistante"
    duration = sf.info(str(audio)).duration
    the_follower = follower(config, identifier)
    lui = assistant_of(config, identifier)
    if lui is None:
        raise RuntimeError("no assistant: check « assistant.actif »")
    if brain is not None:
        lui.cerveau = brain
    if lui.cerveau is None:
        raise RuntimeError("no brain: check « compte_rendu.moteur »")
    lui.context = _live_material(config, identifier, the_follower)
    if hasattr(lui.cerveau, "warm_up"):
        lui.cerveau.warm_up()
    transcriber = light_transcriber(config)
    # As the meeting does: the models open while the room settles.
    _warm_up_aside(lui.voice, transcriber)
    time.sleep(WARM_UP_S)
    # The clock starts with the meeting, once the room has settled.
    clock = Clock()
    _instrumented(lui, clock)
    watcher = Watcher(
        watch_rules=WatchRules(keyword="greffier"),
        log=config.paths.propositions / f"{identifier}.jsonl",
        transcriber=transcriber,
        situer=lambda: Position(chunk=audio, written=min(duration, clock.now()), offset=0.0),
        follower=the_follower,
        language="fr",
        assistant_of=lui,
        speaking=somebody_speaking,
        slice_period=config.live.period,
    )
    with tempfile.TemporaryDirectory() as job:
        watcher.loop(
            still_running=lambda: clock.now() < duration + 2.0,
            since=clock.now,
            job=Path(job),
        )
    if hasattr(lui.cerveau, "close"):
        lui.cerveau.close()
    return clock


def delays(timeline: list[dict[str, Any]], clock: Clock, name: str) -> list[dict[str, Any]]:
    """For each question to her, the three delays, in seconds after its end.

    An event belongs to the last question begun before it: a negative delay
    is her name spotted before the question was over, half a question read.
    """
    rows = []
    questions = [line for line in timeline if str(line["text"]).startswith(name)]
    for question, following in zip(questions, questions[1:] + [None], strict=True):
        begun, end = float(question["start"]), float(question["end"])
        limit = float(following["start"]) if following else float("inf")
        window = [(what, at, detail) for what, at, detail in clock.events if begun <= at < limit]
        first = {what: at for what, at, _ in reversed(window)}
        answer = next((d for w, _, d in window if w == "answered"), "")
        rows.append({
            "question": question["text"],
            "spotted": round(first["spotted"] - end, 2) if "spotted" in first else None,
            "answered": round(first["answered"] - end, 2) if "answered" in first else None,
            "ready": round(first["ready"] - end, 2) if "ready" in first else None,
            "answer": answer,
        })
    return rows


def _keep(file: Path, row: dict[str, Any]) -> None:
    kept = json.loads(file.read_text(encoding="utf-8")) if file.exists() else []
    kept.append(row)
    file.write_text(json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default="", help="the spoken model, default from the settings")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--keep", type=Path, help="append the rows to this JSON file")
    options = parser.parse_args()

    from greffier.adapters.configuration import Config

    with tempfile.TemporaryDirectory() as folder:
        audio, timeline = _meeting(Path(folder))
        for run in range(options.runs):
            config = Config()
            config.paths.data = Path(folder) / f"data-{run}"
            config.assistant.active = True
            config.live.active = True
            clock = replay(audio, config, options.model)
            rows = delays(timeline, clock, config.assistant.name)
            print(f"run {run + 1}, model {config.assistant.model}")
            for row in rows:
                figures = "  ".join(
                    f"{key} {row[key]:5.2f} s" if row[key] is not None else f"{key}   -   "
                    for key in ("spotted", "answered", "ready")
                )
                print(f"  {figures}  {row['question'][:45]!r}")
                print(f"      → {row['answer'][:90]!r}")
            if options.keep:
                _keep(options.keep, {"model": config.assistant.model, "rows": rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
