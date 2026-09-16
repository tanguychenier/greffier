#!/usr/bin/env python3
"""Replays a meeting's live thread with the assistant's initiative on, and logs
every time she would have spoken of her own accord, and what she would have said.

    python3 tools/replay_initiative.py corpus/summre-032a_EARH.live-thread.jsonl
    python3 tools/replay_initiative.py thread.jsonl --period 10 --rest 180

The thread is the file the live thread writes during a meeting (`direct/*.jsonl`,
one turn per line). Time is driven from it, slice by slice: at each period the
assistant sees what was said so far, exactly as `watch.py` hands it over when
`initiative` is on, and decides through the real model. Nothing is spoken; the
interventions go to the terminal and to `<thread>.initiative.json`, with the
moment, what had just been said, and her sentence, so that each one can be
judged: right moment, useful, intrusive.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def turns_of(thread: Path) -> list[dict[str, Any]]:
    turns = []
    for line in thread.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        read = json.loads(line)
        if read.get("genre") == "tour" and read.get("texte"):
            turns.append(read)
    return turns


def rendered(turns: list[dict[str, Any]], up_to: float) -> str:
    """The thread as the assistant reads it, up to this moment."""
    lines: list[str] = []
    current: str | None = None
    for turn in turns:
        if float(turn["fin"]) > up_to:
            break
        who = turn.get("nom") or f"Voix {turn.get('rang') or turn.get('voix')}"
        if who != current:
            lines.append(f"\n[{who}]")
            current = who
        minutes, seconds = divmod(int(float(turn["debut"])), 60)
        lines.append(f"{minutes:02d}:{seconds:02d}  {turn['texte'].strip()}")
    return "\n".join(lines).strip()


def replay(thread: Path, period: float, rest: float, model: str) -> list[dict[str, Any]]:
    from greffier.adapters.brain_claude import ClaudeSession
    from greffier.application.take_part import AssistantSettings
    from greffier.domain.participation import Manners

    turns = turns_of(thread)
    end = max(float(t["fin"]) for t in turns)
    now = {"at": 0.0}
    brain = ClaudeSession(model=model, own_guidance="")
    her = AssistantSettings(
        name="Lucie", brain=brain,
        manners=Manners(active=True, creux_minimal=0.0, rest=rest),
        context=lambda: rendered(turns, now["at"]),
    )
    brain.warm_up()
    interventions: list[dict[str, Any]] = []
    asked = 0
    started = time.monotonic()
    at = period
    while at <= end + period:
        now["at"] = at
        before = time.monotonic()
        opening = her.contribution(at)
        asked += 1
        if opening is not None:
            her.manners.has_spoken(opening, at)
            just_said = rendered(turns, at)[-400:]
            interventions.append({
                "at": round(at, 1), "said": opening.remark,
                "seconds": round(time.monotonic() - before, 1), "just_before": just_said,
            })
            minutes, seconds = divmod(int(at), 60)
            print(f"{minutes:02d}:{seconds:02d}  {opening.remark}", flush=True)
        at += period
    brain.close()
    print(f"\n{len(interventions)} intervention(s) over {end / 60:.0f} min, "
          f"{asked} looks, {time.monotonic() - started:.0f} s of model time", flush=True)
    return interventions


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("thread", type=Path)
    parser.add_argument("--period", type=float, default=10.0, help="seconds between two looks")
    parser.add_argument("--rest", type=float, default=180.0,
                        help="seconds she keeps quiet after having spoken")
    parser.add_argument("--model", default="sonnet")
    options = parser.parse_args()
    interventions = replay(options.thread, options.period, options.rest, options.model)
    output = options.thread.with_suffix(".initiative.json")
    output.write_text(json.dumps(interventions, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
