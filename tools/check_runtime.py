#!/usr/bin/env python3
"""Run a packaged application through its explicit, pixel-free window proof."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def check(command: list[str], destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="greffier-runtime-") as temporary:
        root = Path(temporary)
        environment = dict(os.environ)
        environment.update({
            "GREFFIER_ECRAN_D_ESSAI": "1",
            "GREFFIER_RUNTIME_PROOF_DIR": str(root / "proof"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "LOCALAPPDATA": str(root / "local"),
            "APPDATA": str(root / "roaming"),
        })
        subprocess.run(command, env=environment, check=True, timeout=120)
        result = json.loads((root / "proof" / "runtime-proof.json").read_text(encoding="utf-8"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result["ok"] or len(result["visits"]) != 14 or result["pixels_captured"]:
            raise RuntimeError("The packaged window did not complete its runtime proof.")
        print(f"Window proof passed on {result['system']} for {result['version']}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("an application command is required")
    check(command, arguments.output)


if __name__ == "__main__":
    main()
