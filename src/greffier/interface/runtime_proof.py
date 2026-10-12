"""Exercises only the window created for an explicitly requested runtime proof.

The result describes callbacks and widget geometry. No pixels are captured,
and no other application's windows are inspected.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tkinter as tk
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from greffier.adapters.private_files import write_private_text
from greffier.adapters.updates import installed_version

if TYPE_CHECKING:
    from greffier.interface.window import Window


@dataclass
class Proof:
    window: Window
    destination: Path
    interval_ms: int = 250
    visits: list[dict[str, object]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    finished: bool = False

    def callback_failed(
        self, kind: type[BaseException], value: BaseException, trace: TracebackType | None,
    ) -> None:
        self.errors.append("".join(traceback.format_exception(kind, value, trace)))
        self.finish()

    def visit(self, rank: int = 0) -> None:
        captions = list(self.window.tabs._pages)
        layouts = ((880, 760), (1280, 760))
        if rank == len(captions) * len(layouts):
            self.finish()
            return
        width, height = layouts[rank // len(captions)]
        caption = captions[rank % len(captions)]
        self.window.root.geometry(f"{width}x{height}")
        self.window.tabs.reveal(caption)
        self.window.root.update_idletasks()
        page = self.window.tabs._pages[caption]
        buttons = self._buttons(page)
        for button in buttons:
            parent = button.master
            if (
                parent is not None
                and button.winfo_x() + button.winfo_width() > parent.winfo_width()
            ):
                self.errors.append(f"Un bouton dépasse son parent dans {caption} à {width} pixels.")
        self.visits.append({
            "tab": caption,
            "width": self.window.root.winfo_width(),
            "height": self.window.root.winfo_height(),
            "mapped": bool(page.winfo_ismapped()),
            "buttons": len(buttons),
        })
        self.window.root.after(self.interval_ms, lambda: self.visit(rank + 1))

    def _buttons(self, node: tk.Misc) -> list[tk.Misc]:
        found: list[tk.Misc] = []
        for child in node.winfo_children():
            if child.winfo_ismapped():
                if type(child).__name__ == "Button":
                    found.append(child)
                found.extend(self._buttons(child))
        return found

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        result = {
            "system": platform.system(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "version": installed_version(),
            "ok": not self.errors and bool(self.visits)
            and all(visit["mapped"] for visit in self.visits),
            "visits": self.visits,
            "errors": self.errors,
            "pixels_captured": False,
        }
        try:
            write_private_text(self.destination, json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            self.window.root.destroy()


def schedule(window: Window, folder: Path, interval_ms: int = 250) -> Proof:
    if not os.environ.get("GREFFIER_ECRAN_D_ESSAI"):
        raise ValueError("La preuve doit être lancée avec un environnement d'essai explicite.")
    proof = Proof(window, folder / "runtime-proof.json", interval_ms=interval_ms)
    window.root.report_callback_exception = proof.callback_failed
    window.root.after(interval_ms, proof.visit)
    return proof
