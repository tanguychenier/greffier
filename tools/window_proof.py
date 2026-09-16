#!/usr/bin/env python3
"""Opens the real window, shows every tab, and reports.

Serves the Linux proof of the interface (`tools/window-proof-linux.Dockerfile`),
and runs just as well by hand on any system:

    .venv/bin/python tools/window_proof.py

The window is **really built**, then every tab is shown through its own code,
the method already chosen on macOS, which drives the window rather than
simulating clicks on screen coordinates, too fragile. Nothing is simulated
here: if Tk is missing, if the palette fails, if a tab raises while painting,
this script stops with an error.

What it does not prove: that the window is *pretty*. It proves that it
opens, paints and switches tabs without an exception.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Nobody is in front of this window: it is built to be photographed. Saying so
# keeps the boxes shut, and a box is what stopped this proof dead -- on a
# machine without the models it hung on the question offering to fetch them,
# which is precisely the machine this script exists to photograph.
os.environ.setdefault("GREFFIER_ECRAN_D_ESSAI", "1")


def capture(window: object, target: Path) -> bool:
    """Photographs the window, so that somebody can **look** at it.

    The tests say a tab paints without an exception; they do not say a button
    falls out of the frame. Two buttons were added to the Meetings tab that
    way without anybody seeing that the seventh stuck out of the window,
    invisible and unreachable. A capture costs a second and shows it.

    Two ways of taking it. macOS aims `screencapture` at a region of the screen.
    Elsewhere, `xwd` photographs the window **by its identifier**, which is the
    better of the two: nothing can slide in front of it, and it works on a
    virtual display where there is no screen at all. Without either, it answers
    False rather than complain -- the painting proof itself runs everywhere.
    """
    import shutil
    import subprocess
    import sys as _sys
    import time

    if _sys.platform != "darwin" or shutil.which("screencapture") is None:
        return _capture_by_identifier(window, target)
    root = window.root  # type: ignore[attr-defined]
    # In front, and in front of everything else. `screencapture -R`
    # photographs a **region of the screen**, not a window: the first version
    # of this tool returned a capture of the mail client that sat there,
    # Greffier's window having gone behind during the wait. One was not
    # looking at what one thought, which is worse than not looking.
    root.lift()
    root.attributes("-topmost", True)
    # Two passes and a pause: `update` empties Tk's event queue, but macOS
    # composites afterwards, asynchronously. A capture taken right after a
    # resize showed the window half redrawn, button bar missing while it was
    # well in place, which sends one looking for an interface defect that
    # does not exist.
    root.update()
    time.sleep(0.4)
    root.update()
    # The coordinates **after** the pause: taken before, they date from
    # before the resize and the capture frames beside the window.
    # A little wide: the window's drop shadow spills over its geometry, and a
    # pixel-exact capture cuts the right edge, the one that gives trouble.
    margin = 24
    x = root.winfo_rootx() - margin
    y = root.winfo_rooty() - margin
    width = root.winfo_width() + 2 * margin
    height = root.winfo_height() + 2 * margin
    target.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["screencapture", "-x", "-o", f"-R{x},{y},{width},{height}", str(target)],
        check=False, capture_output=True,
    )
    return done.returncode == 0 and target.exists()


def _capture_by_identifier(window: object, target: Path) -> bool:
    """The X11 way: the window's own pixels, whatever is in front of it.

    `xwd -id` reads the window rather than a region, so a terminal sitting on
    top of it changes nothing -- and on a virtual display, where the proof runs,
    there is nothing in front of anything. ffmpeg converts, being already a
    requirement of the tool.
    """
    import shutil
    import subprocess
    import tempfile

    if not (shutil.which("xwd") and shutil.which("ffmpeg")):
        return False
    root = window.root  # type: ignore[attr-defined]
    root.update()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".xwd") as raw:
        taken = subprocess.run(
            ["xwd", "-id", str(root.winfo_id()), "-out", raw.name],
            check=False, capture_output=True,
        )
        if taken.returncode != 0:
            return False
        # `-pix_fmt rgb24`, otherwise ffmpeg writes an **rgba** PNG whose alpha
        # channel comes from bits X never filled: on screen the image looks
        # washed out, a plain blue button passes for pale blue text and the
        # white cards vanish into the background. A capture one cannot look at
        # is useless, and looking is all that is asked of it.
        converted = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", raw.name, "-pix_fmt", "rgb24", str(target)],
            check=False, capture_output=True,
        )
    return converted.returncode == 0 and target.exists()


def _stop_on_a_callback_exception(kind: object, value: object, trace: object) -> None:
    import traceback

    print("".join(traceback.format_exception(kind, value, trace)), flush=True)  # type: ignore[arg-type]
    os._exit(1)


def main() -> int:
    import tkinter as tk

    from greffier.adapters.configuration import Config
    from greffier.interface.window import Window

    print("tkinter", tk.TkVersion, "- Tcl", tk.TclVersion)

    window = Window(Config())
    # A Tk callback that raises is printed by Tk and forgotten, and the proof
    # went on photographing a window that was broken: here it stops, with
    # the traceback where the log is read.
    window.root.report_callback_exception = _stop_on_a_callback_exception
    # One pass of the event loop: without it nothing is painted yet and a
    # painting exception would go unnoticed.
    window.root.update()
    width = window.root.winfo_width()
    height = window.root.winfo_height()
    print(f"window open: {width}x{height}")

    captions = list(window.tabs._pages)
    for caption in captions:
        window.tabs.reveal(caption)
        window.root.update()
        page = window.tabs._pages[caption]
        print(f"  tab « {caption} » painted, {len(page.winfo_children())} widgets")

    # The count badge draws outside the tests: it touches Tk, which does not
    # start on a continuous integration runner. So this is where it is
    # checked that it shows, widens its tab, and clears when the tab opens.
    window.tabs.reveal(captions[0])
    target = "Conversation" if "Conversation" in captions else captions[-1]
    segment = window.tabs._segments[target]
    bare = int(segment.cget("width"))
    window.tabs.mark(target, 3)
    window.root.update()
    marked = int(segment.cget("width"))
    marks = [
        segment.itemcget(item, "text")
        for item in segment.find_all()
        if segment.type(item) == "text"
    ]
    if marked <= bare or "3" not in marks:
        print(f"  ✗ badge not drawn on « {target} » ({bare} → {marked}, {marks})")
        window.root.destroy()
        return 1
    print(f"  badge on « {target} »: {bare} → {marked} px, mark {marks[-1]}")
    window.tabs.reveal(target)
    window.root.update()
    if int(segment.cget("width")) != bare:
        print("  ✗ the badge survives the opening of its tab")
        window.root.destroy()
        return 1
    print("  badge cleared when the tab opened")

    # One capture per tab, at the minimum width **and** at a comfortable
    # width: narrow is where the button bars overflow, wide is where one sees
    # whether they breathe properly.
    if "--capture" in sys.argv:
        folder = Path(
            sys.argv[sys.argv.index("--capture") + 1]
            if len(sys.argv) > sys.argv.index("--capture") + 1
            else "/tmp/greffier-captures"
        )
        for width, name in ((880, "narrow"), (1280, "wide")):
            for caption in captions:
                # The geometry is restated at **every** tab: switching tabs
                # changes the content, and the window settles back on what
                # that content asks. Set once at the top of the loop, it still
                # held for the first capture and no longer for the next ones,
                # truncated images whose defect is then looked for in the
                # interface instead of the tool.
                window.root.geometry(f"{width}x760")
                window.tabs.reveal(caption)
                window.root.update()
                without_accents = (
                    caption.lower().replace(" ", "-").replace("é", "e")
                )
                target = folder / f"{name}-{without_accents}.png"
                if capture(window, target):
                    print(f"  capture {target}")
                else:
                    print("  capture unavailable on this system")
                    break

    # The guided tour, stop by stop, at both widths: the light and its
    # bubble are looked at on the image, since a light drawn beside its
    # text is exactly what such tours get wrong.
    if "--tour" in sys.argv:
        folder = Path(
            sys.argv[sys.argv.index("--tour") + 1]
            if len(sys.argv) > sys.argv.index("--tour") + 1
            else "/tmp/greffier-captures"
        )
        for width, name in ((880, "narrow"), (1280, "wide")):
            window.root.geometry(f"{width}x760")
            window.tabs.reveal(captions[0])
            window.root.update()
            tour = window.the_tour()
            tour.start()
            for rank in range(len(tour.stops)):
                window.root.update()
                target = folder / f"tour-{name}-{rank + 1:02d}-{tour.stops[rank].key}.png"
                if capture(window, target):
                    print(f"  capture {target}")
                else:
                    print("  capture unavailable on this system")
                    break
                tour.next()
            if tour.running:
                print("  ✗ the tour did not end on its last stop")
                window.root.destroy()
                return 1

    window.root.destroy()
    print(f"{len(captions)} tabs painted without an exception")
    return 0


if __name__ == "__main__":
    sys.exit(main())
