"""The window: an application you launch, not a terminal you learn.

Everything the command line can do has to be reachable here, and what happens
during the meeting has to be correctable while it happens. Long work runs in a
thread and reports back through the state file, so that a model falling over
cannot take the window with it.
"""

from __future__ import annotations

import contextlib
import functools
import math
import platform
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from tkinter import ttk
from typing import Any

from greffier.adapters.configuration import Config
from greffier.adapters.live_levels import LevelReading, read_level
from greffier.application.follow import (
    KIND_CORRECTION,
    KIND_MEETING,
    KIND_STATE,
    ask,
    files,
    read_from,
    replay,
    request_a_split,
)
from greffier.domain.channels import WhoSpeaks
from greffier.domain.emptiness import Missing
from greffier.domain.live import LiveThread, LiveTurn
from greffier.domain.minutes import title
from greffier.domain.models import Phase
from greffier.domain.preparation import Preparation
from greffier.domain.questions import already_noted, note
from greffier.interface import asking
from greffier.interface.appearance import (
    MAIN,
    Button,
    ButtonBar,
    LevelMeter,
    Listing,
    Scroller,
    Tabs,
)
from greffier.interface.readable import clock, live_state_line, readable_subject
from greffier.interface.style import blend, font, palette, title_font
from greffier.locations import locate_tcl

PERIOD_MS = 250

MICROPHONES_PERIOD_MS = 1000

PULSATION_MS = 50

PULSATION_S = 1.6

_LABEL_TEXT = 84

_NOMBRES = frozenset({"voix", "mots", "duree", "part"})

_VOICE_LABELS = {
    WhoSpeaks.NOBODY: "",
    WhoSpeaks.YOU: "tu parles",
    WhoSpeaks.THE_OTHERS: "les autres parlent",
    WhoSpeaks.BOTH: "vous parlez en même temps",
}

@dataclass
class Job:
    """A long task, carried by a thread, reporting back to the window."""

    caption: str
    do_it: Callable[[Callable[[str], None]], Any]
    done: Callable[[Any, Exception | None], None] = lambda _outcome, _trouble: None
    messages: queue.Queue[str] = field(default_factory=queue.Queue)

#: How many tenths of a second the first question may wait for the window to
#: be on screen. A screen that never shows it (a headless session) still gets
#: its question, late rather than never.
PATIENCE_BEFORE_ASKING = 50

class Window:
    """Assembles the interface and keeps it up to date."""

    #: The meeting being prepared, when there is one. Declared here because it
    #: is read before it is written -- the window takes back at startup the one
    #: left waiting yesterday evening.
    _preparation: Preparation | None = None
    #: The microphone while somebody is dictating, and nothing the rest of the
    #: time: its absence is what says that nobody is speaking.
    _dictee: Any | None = None
    #: The registered outside sources, read for the Conversation tab once it
    #: asks, and again only when their reading has gone stale.
    _sources: Any | None = None

    def __init__(self, config: Config) -> None:
        from greffier.wiring import recording, store, troubles

        self.config = config
        self.recorder = recording(config)
        self.store = store(config)
        self.troubles = troubles(config)
        self.colours = palette(config.appearance.theme)
        self.jobs: list[Job] = []
        self._phase_peinte: Phase | None = None
        self._known_microphones: tuple[tuple[str, str], ...] = ()
        self._thread = LiveThread()
        self._questions_seen: set[int] = set()
        self._pending_questions: list[Any] = []
        #: The questions that were on screen while the Conversation tab was
        #: open: the badge counts what has not been looked at, never everything
        #: that is still waiting for an answer.
        self._questions_looked_at: set[int] = set()
        self._learning_pending: Any = None
        self._shown_conversation = ""
        self._apprentissage: Any = None
        self._thread_meeting = ""
        self._thread_position = 0
        self._thread_announcement = ""
        self._menu: tk.Menu | None = None

        locate_tcl()
        self.root = tk.Tk()
        self.root.title("Greffier")
        with contextlib.suppress(tk.TclError):
            self.root.tk.call("tk", "appname", "Greffier")
        self.root.minsize(880, 660)
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)
        self.root.geometry("880x660")
        self.root.configure(bg=self.colours.ground)
        self._style_the_lists()
        self._construire()
        self._refresh()
        self._follow_the_mics()

    def _style_the_lists(self) -> None:
        """The lists stay Tk widgets: at least make them follow the theme."""
        c = self.colours
        style = ttk.Style()
        with contextlib.suppress(tk.TclError):
            style.theme_use("clam")
        style.configure(
            "Greffier.Treeview",
            background=c.board, fieldbackground=c.board, foreground=c.ink,
            borderwidth=0, relief="flat", rowheight=29, font=font(12),
            bordercolor=c.board, lightcolor=c.board, darkcolor=c.board,
        )
        style.configure(
            "Greffier.Treeview.Heading",
            background=c.board, foreground=c.ink_pale, borderwidth=0,
            relief="flat", font=font(11, gras=True), padding=(6, 8),
        )
        style.map("Greffier.Treeview",
                  background=[("selected", c.hover)], foreground=[("selected", c.ink)])
        style.map("Greffier.Treeview.Heading", background=[("active", c.board)])
        style.configure("Greffier.TCombobox", arrowsize=12, padding=6,
                        borderwidth=1, relief="flat", arrowcolor=c.ink_pale,
                        bordercolor=c.rule, lightcolor=c.ground, darkcolor=c.ground,
                        insertcolor=c.ink)
        style.map(
            "Greffier.TCombobox",
            fieldbackground=[("readonly", c.ground)],
            foreground=[("readonly", c.ink), ("disabled", c.calm)],
            selectbackground=[("readonly", c.ground)],
            selectforeground=[("readonly", c.ink)],
            background=[("readonly", c.ground), ("active", c.hover)],
            arrowcolor=[("active", c.ink), ("disabled", c.calm)],
            bordercolor=[("focus", c.ink_pale), ("hover", c.ink_pale)],
        )
        for option, value in (
            ("*TCombobox*Listbox.background", c.board),
            ("*TCombobox*Listbox.foreground", c.ink),
            ("*TCombobox*Listbox.selectBackground", c.hover),
            ("*TCombobox*Listbox.selectForeground", c.ink),
            ("*TCombobox*Listbox.borderWidth", "0"),
            ("*TCombobox*Listbox.highlightThickness", "0"),
            ("*TCombobox*Listbox.font", "TkDefaultFont"),
        ):
            with contextlib.suppress(tk.TclError):
                self.root.option_add(option, value)

    def _text(self, parent: tk.Misc, content: str, size: int = 13,
               gras: bool = False, pale: bool = False, **options: Any) -> tk.Label:
        return tk.Label(
            parent, text=content, bg=parent.cget("bg"), anchor="w",
            fg=self.colours.ink_pale if pale else self.colours.ink,
            font=font(size, gras), **options,
        )

    def _field(self, parent: tk.Misc, width: int | None = None) -> tk.Entry:
        c = self.colours
        options: dict[str, Any] = {} if width is None else {"width": width}
        return tk.Entry(
            parent, relief="flat", bg=c.ground, fg=c.ink, font=font(12),
            insertbackground=c.ink, highlightthickness=1,
            highlightbackground=c.rule, highlightcolor=c.accent, **options,
        )

    def _board(self, parent: tk.Misc, sticky: str = "nsew") -> tk.Frame:
        """A card with a hint of drop shadow."""
        c = self.colours
        ombre = tk.Frame(parent, bg=c.rule)
        ombre.grid(row=0, column=0, sticky=sticky, padx=(3, 0), pady=(3, 0))
        board = tk.Frame(parent, bg=c.board, highlightbackground=c.rule,
                         highlightthickness=1)
        board.grid(row=0, column=0, sticky=sticky, padx=(0, 3), pady=(0, 3))
        return board

    def _construire(self) -> None:
        c = self.colours
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        corps = tk.Frame(self.root, bg=c.ground)
        corps.grid(row=0, column=0, sticky="nsew", padx=24, pady=22)
        corps.columnconfigure(0, weight=1)
        corps.rowconfigure(1, weight=1)

        self._build_state(corps)
        self.tabs = Tabs(corps, c)
        self.tabs.on_reveal = self._looked_at
        self.tabs_shown = {
            "Préparation": self.says("onglets.preparation"),
            "Réunions": self.says("onglets.reunions"),
            "En direct": self.says("onglets.direct"),
            "Voix": self.says("onglets.voix"),
            "Conversation": self.says("onglets.conversation"),
            "Réglages": self.says("onglets.reglages"),
        }
        self.tabs.grid(row=1, column=0, sticky="nsew", pady=(22, 0))
        self._preparation_tab()
        self._meetings_tab()
        self._live_tab()
        self._voices_tab()
        self._conversation_tab()
        self._settings_tab()
        self.status_line = self._text(corps, "", size=11, pale=True)
        self.status_line.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self._report_resumable_meetings()
        self._report_a_newer_bundle()
        # Both of those write a line in the window. The next one opens a box,
        # and a box opened from here is a question asked before there is
        # anything behind it to make sense of the question: on a machine with
        # no models -- a fresh installation, that is -- the very first thing
        # somebody saw of Greffier was « a gigabyte and a half, shall I? » over
        # an empty grey rectangle. `after_idle` runs it once the events that
        # paint the window have been dealt with, and not before. On Windows
        # that is still too early: photographed on a runner, the question
        # stood alone on the desktop, the window only appeared once it was
        # answered. So the question waits until the window can be seen.
        self.root.after_idle(self._offer_the_models_once_seen)

    def _build_state(self, parent: tk.Frame) -> None:
        c = self.colours
        board = self._board(parent, sticky="ew")
        board.columnconfigure(0, weight=1)
        inside = tk.Frame(board, bg=c.board)
        inside.grid(row=0, column=0, sticky="ew", padx=24, pady=22)
        inside.columnconfigure(0, weight=1)

        line = tk.Frame(inside, bg=c.board)
        line.grid(row=0, column=0, sticky="ew")
        line.columnconfigure(1, weight=1)
        self.badge = tk.Canvas(line, width=12, height=12, highlightthickness=0,
                                  bg=c.board)
        self.badge.grid(row=0, column=0, sticky="w", pady=(8, 0))
        self._point = self.badge.create_oval(1, 1, 11, 11, fill=c.calm, outline="")
        self.title = self._text(line, self.says("fenetre.pret"), size=21, gras=True)
        self.title.configure(font=title_font(21))
        self.title.grid(row=0, column=1, sticky="w", padx=(11, 0))
        self.chrono = self._text(line, "", size=27)
        self.chrono.grid(row=0, column=2, sticky="e")

        self.detail = self._text(inside, self.says("fenetre.aucun_enregistrement"),
                                  size=12, pale=True)
        self.detail.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        self.measures = measures = tk.Frame(inside, bg=c.board)
        measures.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        measures.columnconfigure(1, weight=1)
        self.seen_you = self._meter_line(measures, "Toi", 0)
        self.seen_others = self._meter_line(measures, "Les autres", 1)
        self.who = self._text(measures, "", size=11, gras=True)
        self.who.configure(fg=c.green)
        self.who.grid(row=2, column=1, sticky="w", pady=(7, 0))

        self.commands = tk.Frame(inside, bg=c.board)
        self.commands.grid(row=3, column=0, sticky="ew", pady=(20, 0))
        self._build_commands()
        self._breathe()

    def _meter_line(self, parent: tk.Frame, caption: str, rank: int) -> LevelMeter:
        self._text(parent, caption, size=11, pale=True).grid(
            row=rank, column=0, sticky="w", pady=3
        )
        parent.columnconfigure(0, minsize=_LABEL_TEXT)
        bar = LevelMeter(parent, self.colours, width=340)
        bar.grid(row=rank, column=1, sticky="w", pady=3)
        return bar

    def _build_commands(self) -> None:
        """The three sets of commands, built once, shown by state."""
        c = self.colours
        self.jeux: dict[Phase, tk.Frame] = {}

        rest = tk.Frame(self.commands, bg=c.board)
        Button(rest, self.says("fenetre.demarrer"), self._start_recording, c,
               principal=True, width=192, height=38).pack(side="left")
        self._text(rest, self.says("fenetre.micro"), size=11, pale=True).pack(
            side="left", padx=(20, 8)
        )
        self.mic = Listing(rest, c, width=286, height=36)
        self.mic.pack(side="left")
        self._load_mics()
        self.jeux[Phase.REST] = rest

        in_progress = tk.Frame(self.commands, bg=c.board)
        Button(in_progress, "Mettre en pause", self._pause, c,
               width=156, height=38).pack(side="left", padx=(0, 10))
        Button(in_progress, self.says("fenetre.terminer"), self._terminate, c,
               principal=True, width=192, height=38).pack(side="left")
        self.jeux[Phase.RECORDING] = in_progress

        pause = tk.Frame(self.commands, bg=c.board)
        Button(pause, "Reprendre", self._resume, c, principal=True,
               width=136, height=38).pack(side="left", padx=(0, 10))
        Button(pause, self.says("fenetre.terminer"), self._terminate, c,
               width=192, height=38).pack(side="left")
        self.jeux[Phase.PAUSE] = pause

        self._show_commands(Phase.REST)

    def _show_commands(self, phase: Phase) -> None:
        """Shows only the commands that make sense in this state."""
        voulu = self.jeux.get(phase, self.jeux[Phase.REST])
        for jeu in self.jeux.values():
            if jeu is voulu:
                jeu.pack(fill="x", anchor="w")
            else:
                jeu.pack_forget()

    def says(self, key: str, **parts: object) -> str:
        """What the tool says, in the language it speaks.

        Read once at build time: a window does not change language while it is
        open, and asking the catalogue on every paint would cost a file read per
        frame for a sentence that never moves.
        """
        wording = getattr(self, "_wording", None)
        if wording is None:
            from greffier.wiring import wording as catalogue

            wording = catalogue(self.config)
            self._wording = wording
        return wording.say(key, **parts)

    def _page(self, caption: str) -> tk.Frame:
        page = self.tabs.add(caption, getattr(self, "tabs_shown", {}).get(caption, ""))
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        board = self._board(page)
        board.columnconfigure(0, weight=1)
        board.rowconfigure(0, weight=1)
        inside = tk.Frame(board, bg=self.colours.board)
        inside.grid(row=0, column=0, sticky="nsew", padx=20, pady=18)
        inside.columnconfigure(0, weight=1)
        return inside

    def _listing(self, parent: tk.Frame, colonnes: tuple[tuple[str, str, int], ...],
               rank: int = 0) -> ttk.Treeview:
        arbre = ttk.Treeview(
            parent, columns=[x[0] for x in colonnes], show="headings",
            style="Greffier.Treeview", selectmode="browse", takefocus=False,
        )
        for indice, (cle, caption, width) in enumerate(colonnes):
            if cle in _NOMBRES:
                arbre.heading(cle, text=caption, anchor="e")
                arbre.column(cle, width=width, anchor="e", stretch=False)
            else:
                arbre.heading(cle, text=caption, anchor="w")
                arbre.column(cle, width=width, anchor="w", stretch=indice == 0)
        arbre.grid(row=rank, column=0, sticky="nsew")
        scrollbar = Scroller(parent, self.colours, arbre.yview)
        scrollbar.grid(row=rank, column=1, sticky="ns", padx=(4, 0))
        arbre.configure(yscrollcommand=scrollbar.set)
        parent.columnconfigure(1, minsize=12)
        parent.rowconfigure(rank, weight=1)
        return arbre

    def _guidance(self, parent: tk.Frame, rank: int) -> tk.Label:
        """The sentence that takes an empty table's place.

        In the table's own cell, hidden as long as there is something to show:
        an empty grid says only what the eye has already seen.
        """
        said = self._text(parent, "", size=12, pale=True,
                          wraplength=700, justify="left")
        said.grid(row=rank, column=0, sticky="nw", pady=(30, 0))
        said.grid_remove()
        return said

    def _say_what_is_missing(
        self, missing: Missing | None, table: ttk.Treeview,
        said: tk.Label, buttons: list[Button],
    ) -> None:
        """Shows the sentence in place of the table, and holds the buttons."""
        from greffier.domain.emptiness import may_act

        sentences = {
            Missing.NO_MEETING_YET: "vide.aucune_reunion",
            Missing.NO_MEETING_CHOSEN: "vide.aucune_reunion_choisie",
            Missing.NO_VOICE_TO_NAME: "vide.aucune_voix",
        }
        for button in buttons:
            button.activer(may_act(missing))
        if missing is None:
            said.grid_remove()
            table.grid()
            return
        table.grid_remove()
        said.configure(text=self.says(sentences[missing]))
        said.grid()

    def _meetings_tab(self) -> None:
        inside = self._page("Réunions")
        self.listing = self._listing(inside, (
            ("date", "Réunion", 320), ("voix", "Personnes", 90),
            ("mots", "Mots", 80), ("compte_rendu", "Compte rendu", 120),
        ))
        self.meeting_guidance = self._guidance(inside, rank=0)
        actions = ButtonBar(inside, self.colours)
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        self.meeting_buttons = []
        for caption, action, width, principal in (
            ("Traiter", self._process_selection, 100, False),
            ("Rédiger", self._write_up_selection, 100, False),
            ("Ouvrir", self._open_minutes, 96, False),
            ("Envoyer par courriel", self._send_selection, 180, False),
            ("Déposer…", self._drop_files, 116, False),
            ("Renommer", self._rename_selection, 110, False),
            ("Exporter…", self._export_selection, 110, False),
            ("Rafraîchir", self._load_meetings, 116, False),
        ):
            button = Button(actions, caption, action, self.colours,
                            principal=principal, width=width, height=34)
            if caption == "Traiter":
                button._en_avant()
            if caption != "Rafraîchir":
                self.meeting_buttons.append(button)
            actions.add(button, width)
        apart = tk.Frame(inside, bg=self.colours.board)
        apart.grid(row=2, column=0, sticky="e", pady=(10, 0))
        supprimer = Button(apart, "Supprimer", self._forget_selection, self.colours,
                           width=110, height=30)._efface()
        supprimer.pack(side="right")
        self.meeting_buttons.append(supprimer)
        self.listing.bind("<<TreeviewSelect>>", lambda _e: self._load_voices())
        self._load_meetings()

    def _live_tab(self) -> None:
        """What is being said, while it is said, and correctable there."""
        c = self.colours
        inside = self._page("En direct")
        self.live_state = self._text(
            inside,
            self.says("direct.mode_emploi"),
            size=11, pale=True, wraplength=740, justify="left",
        )
        self.live_state.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        bar = tk.Frame(inside, bg=c.board)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.voice_button = Button(
            bar, self._voice_caption(), self._toggle_the_voice, self.colours,
            width=230, height=34,
            principal=self.config.assistant.voice != "aucun")
        self.voice_button.grid(row=0, column=0, sticky="w")
        self.initiative_button = Button(
            bar, self._initiative_caption(), self._toggle_initiative,
            self.colours, width=250, height=34,
            principal=self.config.assistant.initiative)
        self.initiative_button.grid(row=0, column=1, sticky="w", padx=(10, 0))
        Button(bar, "Fournir un document", self._supply_a_document,
               self.colours, width=190, height=34).grid(
                   row=0, column=2, sticky="w", padx=(10, 0))
        self.participation_line = self._text(
            inside, "", size=11, pale=True, wraplength=740, justify="left")
        self.participation_line.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._say_the_participation()

        frame = tk.Frame(inside, bg=c.board)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        inside.rowconfigure(3, weight=1)

        self.thread_widget = tk.Text(
            frame, wrap="word", relief="flat", bg=c.board, fg=c.ink,
            padx=0, pady=0, font=font(12), state="disabled",
            highlightthickness=0, cursor="arrow", spacing3=6,
        )
        self.thread_widget.grid(row=0, column=0, sticky="nsew")
        scrollbar = Scroller(frame, c, self.thread_widget.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.thread_widget.configure(yscrollcommand=scrollbar.set)
        self.thread_widget.tag_configure("heure", foreground=c.calm, font=font(10))
        self.thread_widget.tag_configure("sur", foreground=c.ink, font=font(11, gras=True))
        self.thread_widget.tag_configure("doute", foreground=c.amber, font=font(11, gras=True))
        self.thread_widget.tag_configure("dit", foreground=c.ink, lmargin2=90)

    def _voice_caption(self) -> str:
        name = self.config.assistant.name
        return (f"Couper la voix de {name}"
                if self.config.assistant.voice != "aucun"
                else f"Donner la voix à {name}")

    def _toggle_the_voice(self) -> None:
        """Gives it the floor, or takes it away, without silencing it.

        Cut here and now rather than through the setting: the watch is another process
        and only re-reads it at the next slice, up to fifteen seconds later. Measured
        in a meeting, you press, it keeps talking, and the button looks broken.
        """
        from greffier.adapters import configuration as settings
        from greffier.adapters.voice_neural import NeuralVoice, silence

        avant = self.config.assistant.voice
        if avant != "aucun":
            silence(self.config.paths.gag)
            self.config.assistant.voice = "aucun"
        else:
            self.config.assistant.voice = (
                "kokoro"
                if NeuralVoice(self.config.paths.synthetic_voice).installed
                else "systeme"
            )
        try:
            settings.save_settings(self.config)
        except OSError as trouble:
            self.config.assistant.voice = avant
            asking.complain("Greffier", f"Réglage non enregistré : {trouble}")
            return
        self.voice_button.set_caption(self._voice_caption())
        self.voice_button.highlight(self.config.assistant.voice != "aucun")
        self._say_the_participation()
        if hasattr(self, "assistant_voice_setting"):
            self.assistant_voice_setting.choose(self.config.assistant.voice)

    def _initiative_caption(self) -> str:
        name = self.config.assistant.name
        return (f"{name} n'intervient que si on l'appelle"
                if self.config.assistant.initiative
                else f"Laisser {name} intervenir d'elle-même")

    def _toggle_initiative(self) -> None:
        """Lets it speak without being called, or takes that away."""
        from greffier.adapters import configuration as settings

        avant = self.config.assistant.initiative
        self.config.assistant.initiative = not avant
        try:
            settings.save_settings(self.config)
        except OSError as trouble:
            self.config.assistant.initiative = avant
            asking.complain("Greffier", f"Réglage non enregistré : {trouble}")
            return
        self.initiative_button.set_caption(self._initiative_caption())
        self.initiative_button.highlight(self.config.assistant.initiative)
        self._say_the_participation()

    def _say_the_participation(self) -> None:
        """What the button just changed, in plain words."""
        name = self.config.assistant.name
        if self.config.assistant.voice == "aucun":
            word = (f"{name} suit la réunion et pose ses questions dans l'onglet "
                   "Conversation : répondez-lui au clavier.")
        else:
            word = (f"{name} peut prendre la parole. Appelez-la par son nom pour "
                   "lui poser une question.")
        word += (" Elle peut aussi intervenir d'elle-même."
                if self.config.assistant.initiative
                else " Elle n'intervient jamais sans qu'on l'appelle.")
        self.participation_line.configure(text=word)

    def _follow_the_live_thread(self, state: Any) -> None:
        """Reads what the listening process published since last time."""
        if state.identifier != self._thread_meeting:
            self._forget_the_live_thread(state.identifier)
        if not self._thread_meeting:
            return
        log, _ = files(self.config.paths.live, self._thread_meeting)
        lines, self._thread_position = read_from(log, self._thread_position)
        if not lines:
            return
        for line in lines:
            if line.get("genre") == KIND_STATE:
                self._thread_announcement = str(line.get("message", ""))
        already = len(self._thread.turns)
        remaniement = {KIND_CORRECTION, KIND_MEETING}
        corrige = any(line.get("genre") in remaniement for line in lines)
        replay(lines, self._thread)
        if corrige:
            self._repaint_the_live_tab()
        else:
            self._add_to_live(self._thread.turns[already:])
        self._say_the_live_state()
        self._follow_the_questions()

    def _follow_the_questions(self) -> None:
        """Shows what the tool is asking, and puts the count on the tab."""
        from greffier.adapters import questions_file

        if not self._thread_meeting:
            return
        file = questions_file.questions_file(
            self.config.paths.questions, self._thread_meeting
        )
        awaiting, _ = questions_file.read(file)
        for waiting in awaiting:
            if waiting.number in self._questions_seen:
                continue
            self._questions_seen.add(waiting.number)
            self._say("note", note(waiting.question.text))
            self._say("note", self.says("direct.repondre_a_la_question"))
        self._pending_questions = awaiting
        self._flag_the_unseen_questions()

    def _looked_at(self, caption: str) -> None:
        """What was on the tab just opened has now been seen."""
        if caption == "Conversation":
            self._questions_looked_at |= {q.number for q in self._pending_questions}

    def _flag_the_unseen_questions(self) -> None:
        """Puts on the Conversation tab the questions nobody has looked at yet.

        Reported in use: read a question, switch tab, one more arrives, and the
        badge said three where one was new. A badge that counts everything
        pending tells nothing about what changed.
        """
        if self.tabs.current == "Conversation":
            self._questions_looked_at |= {q.number for q in self._pending_questions}
        unseen = [q for q in self._pending_questions if q.number not in self._questions_looked_at]
        self.tabs.mark("Conversation", len(unseen))

    def _questions_already_noted(self, identifier: str) -> set[int]:
        """The questions this meeting's conversation already carries."""
        from greffier.adapters import conversations_file, questions_file

        if not identifier:
            return set()
        awaiting, _ = questions_file.read(questions_file.questions_file(
            self.config.paths.questions, identifier))
        conversation = conversations_file.read(
            conversations_file.file_for(self.config.paths.conversations,
                                        identifier),
            derniers=0,
        )
        return already_noted(
            [waiting.question for waiting in awaiting],
            [turn.text for turn in conversation],
        )

    def _forget_the_live_thread(self, identifier: str) -> None:
        """Starts over: another meeting, another thread."""
        self._thread = LiveThread()
        self._thread_meeting = identifier
        self._thread_position = 0
        self._thread_announcement = ""
        self._questions_seen = self._questions_already_noted(identifier)
        self._pending_questions = []
        self._questions_looked_at = set()
        self.tabs.mark("Conversation", 0)
        self._shown_conversation = ""
        self._load_the_conversation()
        self._empty_out(self.thread_widget)
        self._say_the_live_state()

    def _say_the_live_state(self) -> None:
        self.live_state.configure(
            text=live_state_line(
                in_a_meeting=bool(self._thread_meeting),
                annonce=self._thread_announcement,
                sentences=len(self._thread.turns),
            )
        )

    def _empty_out(self, zone: tk.Text) -> None:
        zone.configure(state="normal")
        zone.delete("1.0", "end")
        zone.configure(state="disabled")

    def _repaint_the_live_tab(self) -> None:
        self._empty_out(self.thread_widget)
        self._add_to_live(self._thread.turns)

    def _add_to_live(self, turns: list[LiveTurn]) -> None:
        if not turns:
            return
        suivait = self.thread_widget.yview()[1] > 0.999
        self.thread_widget.configure(state="normal")
        for turn in turns:
            self._write_a_turn(turn)
        self.thread_widget.configure(state="disabled")
        if suivait:
            self.thread_widget.see("end")

    def _write_a_turn(self, turn: LiveTurn) -> None:
        voice = self._thread.voice.get(turn.voice)
        firm = voice is not None and voice.certainty.firm
        repere = f"tour{turn.number}"
        self.thread_widget.insert("end", f"{clock(turn.span.start)}  ", "heure")
        self.thread_widget.insert(
            "end", self._thread.label(turn.voice), ("sur" if firm else "doute", repere)
        )
        self.thread_widget.insert("end", f"   {turn.text}\n", "dit")
        self.thread_widget.tag_bind(
            repere, "<Button-1>",
            functools.partial(self._speaker_menu, number=turn.number),
        )
        self.thread_widget.tag_bind(
            repere, "<Enter>", lambda _e: self.thread_widget.configure(cursor=MAIN)
        )
        self.thread_widget.tag_bind(
            repere, "<Leave>", lambda _e: self.thread_widget.configure(cursor="arrow")
        )

    def _speaker_menu(self, event: Any, number: int) -> None:
        """The correction menu: who is really speaking."""
        turn = next((t for t in self._thread.turns if t.number == number), None)
        if turn is None:
            return
        voice = self._thread.voice.get(turn.voice)
        names = self._thread.suggestable_names()
        menu = tk.Menu(self.root, tearoff=0, font=font(12))
        if voice is not None and voice.nameable:
            menu.add_command(
                label=f"Toute la voix « {self._thread.label(turn.voice)} » est :",
                state="disabled",
            )
            if voice.confidence:
                menu.add_command(label=f"   {voice.confidence}", state="disabled")
                menu.add_separator()
            self._fill_menu(menu, names, number, whole_voice=True)
            menu.add_separator()
            sentence = tk.Menu(menu, tearoff=0, font=font(12))
            self._fill_menu(sentence, names, number, whole_voice=False)
            menu.add_cascade(label="Seulement cette phrase…", menu=sentence)
            if self._thread.can_split(turn.voice):
                menu.add_separator()
                menu.add_command(
                    label="Ce n'est pas la même personne : séparer les deux voix",
                    command=functools.partial(self._split_in_the_live_thread, turn.voice),
                )
        else:
            menu.add_command(label="Cette phrase est de :", state="disabled")
            self._fill_menu(menu, names, number, whole_voice=False)
        self._menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _fill_menu(
        self, menu: tk.Menu, names: list[str], number: int, whole_voice: bool
    ) -> None:
        elsewhere = self._names_held_elsewhere(number)
        for name in names:
            suffixe = "   ⟵ réunir les deux voix" if name in elsewhere else ""
            menu.add_command(
                label=f"{name}{suffixe}",
                command=functools.partial(
                    self._correct_the_live_thread, number, name, whole_voice
                ),
            )
        menu.add_command(
            label="Autre nom…",
            command=functools.partial(self._ask_for_a_name, number, whole_voice),
        )

    def _names_held_elsewhere(self, number: int) -> set[str]:
        """The names already held by **another** voice than this one."""
        turn = next((t for t in self._thread.turns if t.number == number), None)
        return {
            voice.name for identifier, voice in self._thread.voice.items()
            if voice.name and (turn is None or identifier != turn.voice)
        }

    def _ask_for_a_name(self, number: int, whole_voice: bool) -> None:
        from tkinter import simpledialog

        name = simpledialog.askstring(
            "Greffier", "Qui parle ?", parent=self.root
        )
        if name and name.strip():
            self._correct_the_live_thread(number, name.strip(), whole_voice)

    def _split_in_the_live_thread(self, identifier: str) -> None:
        """Undoes the last join that produced this voice."""
        defaite = self._thread.split(identifier)
        if defaite is None:
            asking.tell(
                "Greffier", self.says("voix.rien_a_separer")
            )
            return
        _, requests = files(self.config.paths.live, self._thread_meeting)
        try:
            request_a_split(requests, identifier)
        except OSError as trouble:
            asking.complain(
                "Greffier",
                f"La séparation est affichée mais n'a pas pu être transmise : {trouble}",
            )
        self._repaint_the_live_tab()
        rendue = self._thread.label(defaite.source)
        self.status_line.configure(
            text=f"Les deux voix sont séparées. « {rendue} » attend un nom."
        )

    def _correct_the_live_thread(self, number: int, name: str, whole_voice: bool) -> None:
        """Applies the correction here, and passes it to whoever is listening.

        Here first: a click has to show at once, not in ten seconds.
        """
        try:
            self._thread.correct(number, name, whole_voice)
        except (KeyError, ValueError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        _, requests = files(self.config.paths.live, self._thread_meeting)
        try:
            ask(requests, number, name, whole_voice)
        except OSError as trouble:
            asking.complain(
                "Greffier",
                f"La correction est affichée mais n'a pas pu être transmise : {trouble}",
            )
        self._repaint_the_live_tab()

    def _voices_tab(self) -> None:
        inside = self._page("Voix")
        self._text(
            inside,
            self.says("voix.mode_emploi"),
            size=11, pale=True, wraplength=740, justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.voice = self._listing(inside, (
            ("voix", "Voix", 100), ("duree", "Durée", 90),
            ("part", "Part", 80), ("nom", "Nom", 260),
        ), rank=1)
        self.voice_guidance = self._guidance(inside, rank=1)

        entry = tk.Frame(inside, bg=self.colours.board)
        entry.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        entry.columnconfigure(2, weight=1)
        self._text(entry, self.says("voix.prenom"), size=11, pale=True).grid(
            row=0, column=0, sticky="w", padx=(0, 9)
        )
        self.name_field = self._field(entry, width=20)
        self.name_field.grid(row=0, column=1, sticky="w", ipady=7, ipadx=5)
        self.name_field.bind("<Return>", lambda _e: self._name_voice())
        # A bar that wraps, not four buttons packed side by side: at 880 px,
        # the narrowest the window can be, « Séparer les deux voix » ran past
        # the edge of the card with its last word cut off, reachable by nobody.
        # The Réunions tab has wrapped its seven buttons since the day the
        # seventh disappeared the same way.
        actions = ButtonBar(entry, self.colours)
        actions.grid(row=0, column=2, sticky="ew", padx=(11, 0))
        self.voice_buttons = []
        for caption, action, width, principal in (
            ("Nommer", self._name_voice, 110, True),
            ("Écouter 10 s", self._listen, 140, False),
            ("Retirer le nom", self._forget_the_name, 150, False),
            ("Séparer les deux voix", self._split_the_voice, 190, False),
        ):
            button = Button(actions, caption, action, self.colours,
                            principal=principal, width=width, height=34)
            actions.add(button, width)
            self.voice_buttons.append(button)

        # Set apart and a line below, like « Supprimer » in the Réunions tab:
        # this one erases a person from every meeting at once, and a gesture of
        # that weight does not belong in a row with « Écouter 10 s ».
        apart = tk.Frame(inside, bg=self.colours.board)
        apart.grid(row=3, column=0, sticky="e", pady=(10, 0))
        self.forget_button = Button(
            apart, "Oublier la personne", self._forget_a_person, self.colours,
            width=180, height=30,
        )._efface()
        self.forget_button.pack(side="right")

    def _preparation_tab(self) -> None:
        """Before a meeting: what to raise, who is expected, and Lucie.

        Its own tab and not a corner of the conversation: preparing is a moment
        of the work, between « nothing yet » and « recording ». Put inside the
        conversation it was a feature of a chat; put here it is the first step.
        """
        c = self.colours
        inside = self._page("Préparation")
        inside.rowconfigure(2, weight=1)

        header = tk.Frame(inside, bg=c.board)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.prepare_button = Button(
            header, self.says("conversation.preparer"), self._open_a_preparation,
            self.colours, width=250, height=34)
        self.prepare_button.grid(row=0, column=0)
        self.preparation_line = tk.Label(
            header, text="", bg=c.board, fg=c.ink_pale, font=font(11),
            anchor="w", justify="left")
        self.preparation_line.grid(row=0, column=1, sticky="w", padx=(12, 0))

        listes = tk.Frame(inside, bg=c.board)
        listes.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        listes.columnconfigure(1, weight=1)
        listes.columnconfigure(3, weight=1)
        tk.Label(listes, text=self.says("preparation.attendus"), bg=c.board,
                 fg=c.ink_pale, font=font(11)).grid(row=0, column=0, sticky="w")
        self.expected_field = self._field(listes)
        self.expected_field.grid(row=0, column=1, sticky="ew", padx=(8, 8), ipady=5)
        self.expected_field.bind("<Return>", lambda _e: self._expect_someone())
        tk.Label(listes, text=self.says("preparation.a_soulever"), bg=c.board,
                 fg=c.ink_pale, font=font(11)).grid(row=0, column=2, sticky="w")
        self.point_field = self._field(listes)
        self.point_field.grid(row=0, column=3, sticky="ew", padx=(8, 0), ipady=5)
        self.point_field.bind("<Return>", lambda _e: self._raise_a_point())

        frame = tk.Frame(inside, bg=c.board)
        frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.fil_preparation = tk.Text(
            frame, wrap="word", relief="flat", bg=c.board, fg=c.ink, padx=0, pady=0,
            font=font(12), state="disabled", highlightthickness=0, cursor="arrow")
        self.fil_preparation.grid(row=0, column=0, sticky="nsew")
        barre = Scroller(frame, c, self.fil_preparation.yview)
        barre.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.fil_preparation.configure(yscrollcommand=barre.set)
        self.fil_preparation.tag_configure(
            "qui", foreground=c.ink_pale, spacing1=12, spacing3=3,
            font=font(10, gras=True))
        self.fil_preparation.tag_configure("dit", foreground=c.ink, spacing3=8)
        self.fil_preparation.tag_configure(
            "note", foreground=c.ink_pale, spacing1=5, spacing3=10, font=font(11))

        bas = tk.Frame(inside, bg=c.board)
        bas.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        bas.columnconfigure(0, weight=1)
        self.question_preparation = self._field(bas)
        self.question_preparation.grid(row=0, column=0, sticky="ew", ipady=8, ipadx=5)
        self.question_preparation.bind(
            "<Return>", lambda _e: self._ask_while_preparing())
        Button(bas, self.says("conversation.demander"), self._ask_while_preparing,
               self.colours, principal=True, width=110, height=36).grid(
                   row=0, column=1, padx=(11, 0))
        self.speak_button = Button(
            bas, self.says("conversation.parler"), self._speak_or_stop,
            self.colours, width=150, height=36)
        self.speak_button.grid(row=0, column=2, padx=(8, 0))
        Button(bas, self.says("conversation.fournir_un_document"),
               self._supply_a_document, self.colours, width=176, height=36).grid(
                   row=0, column=3, padx=(8, 0))
        Button(bas, self.says("commun.vider"), self._clear_the_preparation_thread,
               self.colours, width=90, height=36).grid(row=0, column=4, padx=(8, 0))
        self._say_while_preparing("note", self.says("preparation.mode_emploi"))

    def _ask_while_preparing(self) -> None:
        question = self.question_preparation.get().strip()
        if not question:
            return
        self.question_preparation.delete(0, "end")
        self._ensure_a_preparation()
        self._answer_while_preparing(question)

    def _ensure_a_preparation(self) -> None:
        """Opens one on the first question rather than demanding a click first."""
        from greffier.adapters import preparations_file

        if getattr(self, "_preparation", None) is not None:
            return
        self._preparation = preparations_file.open_one(self._preparations_folder(), "")
        self._paint_the_preparation()

    def _expect_someone(self) -> None:
        name = self.expected_field.get().strip()
        if not name:
            return
        self.expected_field.delete(0, "end")
        self._ensure_a_preparation()
        preparation = self._preparation
        if preparation is None:
            return
        self._preparation = preparation.expecting(name)
        self._keep_the_preparation()
        self._say_while_preparing("note", self.says("preparation.attendu_note", who=name))

    def _raise_a_point(self) -> None:
        point = self.point_field.get().strip()
        if not point:
            return
        self.point_field.delete(0, "end")
        self._ensure_a_preparation()
        preparation = self._preparation
        if preparation is None:
            return
        self._preparation = preparation.raising(point)
        self._keep_the_preparation()
        self._say_while_preparing("note", self.says("preparation.point_note", what=point))

    def _say_while_preparing(self, who: str, text: str) -> None:
        fil = getattr(self, "fil_preparation", None)
        if fil is None:
            return
        fil.configure(state="normal")
        if who in ("moi", "greffier"):
            fil.insert("end", "TOI\n" if who == "moi" else "LUCIE\n", "qui")
            fil.insert("end", f"{text}\n", "dit")
        else:
            fil.insert("end", f"{text}\n", "note")
        fil.see("end")
        fil.configure(state="disabled")

    def _clear_the_preparation_thread(self) -> None:
        """Empties what is shown. What was gathered stays gathered."""
        fil = getattr(self, "fil_preparation", None)
        if fil is None:
            return
        fil.configure(state="normal")
        fil.delete("1.0", "end")
        fil.configure(state="disabled")
        self._say_while_preparing("note", self.says("preparation.mode_emploi"))

    def _conversation_tab(self) -> None:
        c = self.colours
        inside = self._page("Conversation")
        frame = tk.Frame(inside, bg=c.board)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        inside.rowconfigure(0, weight=1)

        self.thread = tk.Text(frame, wrap="word", relief="flat", bg=c.board, fg=c.ink,
                           padx=0, pady=0, font=font(12), state="disabled",
                           highlightthickness=0, cursor="arrow")
        self.thread.grid(row=0, column=0, sticky="nsew")
        scrollbar = Scroller(frame, c, self.thread.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.thread.configure(yscrollcommand=scrollbar.set)
        self.thread.tag_configure("qui", foreground=c.ink_pale, spacing1=12, spacing3=3,
                               font=font(10, gras=True))
        self.thread.tag_configure("dit", foreground=c.ink, spacing3=8)
        self.thread.tag_configure("note", foreground=c.ink_pale, spacing1=5, spacing3=10,
                               font=font(11))

        entry = tk.Frame(inside, bg=c.board)
        entry.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        entry.columnconfigure(0, weight=1)
        self.question = self._field(entry)
        self.question.grid(row=0, column=0, sticky="ew", ipady=8, ipadx=5)
        self.question.bind("<Return>", lambda _e: self._ask())
        Button(entry, self.says("conversation.demander"), self._ask, self.colours, principal=True,
               width=124, height=36).grid(row=0, column=1, padx=(11, 0))
        Button(entry, self.says("conversation.fournir_un_document"), self._supply_a_document,
               self.colours, width=176, height=36).grid(
                   row=0, column=2, padx=(8, 0))
        Button(entry, self.says("commun.vider"), self._clear_the_thread,
               self.colours, width=90, height=36).grid(row=0, column=3, padx=(8, 0))
        self._paint_the_turn(
            "note",
            self.says("conversation.mode_emploi"),
        )
        self._paint_the_turn("note", self.says("conversation.avant_une_reunion"))
        self._paint_the_turn(
            "note",
            self.says("conversation.apprendre"),
        )

    TRANSCRIPTION_MODELS = (
        ("large-v3-turbo", "large-v3-turbo : le plus juste, conseillé"),
        ("large-v3", "large-v3 : plus lent, sans gain mesuré ici"),
        ("small", "small : rapide, pour les postes modestes"),
    )
    THEMES = (("systeme", "Selon le système"), ("clair", "Clair"), ("sombre", "Sombre"))
    LANGUAGES = (
        ("fr", "Français"), ("", "Détection automatique"), ("en", "Anglais"),
        ("es", "Espagnol"), ("de", "Allemand"), ("it", "Italien"),
        ("pt", "Portugais"), ("nl", "Néerlandais"), ("ca", "Catalan"),
        ("pl", "Polonais"), ("ro", "Roumain"), ("ru", "Russe"),
        ("tr", "Turc"), ("ar", "Arabe"), ("zh", "Chinois"), ("ja", "Japonais"),
    )
    MOTEURS_REDACTION = (
        ("claude", "Claude Code : la meilleure synthèse"),
        ("ollama", "Ollama : tout reste sur ce poste"),
        ("aucun", "Aucun : s'arrêter à la transcription"),
    )
    ATTENDEES = (("", "Déduit de l'enregistrement"),
                    *((str(n), f"{n} personnes") for n in range(2, 13)))
    PERIODES_DIRECT = (("5.0", "5 s : très réactif, plus de calcul"),
                       ("10.0", "10 s : conseillé"),
                       ("20.0", "20 s : économe, l'affichage suit de loin"))

    def _settings_tab(self) -> None:
        """The settings people actually change, without opening a file."""
        page = self._page("Réglages")
        header = tk.Frame(page, bg=self.colours.board)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        self.settings_word = self._text(
            header, self.says("reglages.applique_aussitot"),
            size=11, pale=True)
        self.settings_word.grid(row=0, column=0, sticky="w")
        inside = self._scrolling_area(page)

        rank = 0
        rank = self._block(inside, rank, "Micro", "Celui que Greffier prend au démarrage.")
        self.microphone_setting = self._dropdown(inside, rank, "Appareil")
        rank += 1

        rank = self._block(inside, rank, "Participants",
                          "Le nombre de personnes autour de la table, si vous le connaissez.")
        self.attendees_setting = self._dropdown(inside, rank, "Personnes",
                                                          width=232)
        rank += 1

        rank = self._block(inside, rank, "Transcription",
                          "Le modèle de la transcription définitive, faite après la réunion.")
        self.model_setting = self._dropdown(inside, rank, "Modèle")
        rank += 1
        self.language_setting = self._dropdown(inside, rank, "Langue", width=232)
        rank += 1

        rank = self._block(inside, rank, "Compte Claude",
                          "C'est lui qui rédige : sans session ouverte, tout marche "
                          "sauf le compte rendu.")
        self.account_word = self._text(inside, "", size=11)
        self.account_word.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 5))
        rank += 1
        buttons = tk.Frame(inside, bg=self.colours.board)
        buttons.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self.session_button = Button(buttons, "Se connecter", self._claude_session,
                                     self.colours, width=228, height=32)
        self.session_button.pack(side="left", padx=(0, 9))
        self.update_button = Button(buttons, self.says("reglages.maj_claude"),
                                 self._update_claude,
                                 self.colours, width=228, height=32)
        self.update_button.pack(side="left")
        rank += 1

        rank = self._block(inside, rank, "Modèles locaux",
                          "Ils vivent hors de l'application : une mise à jour "
                          "ne les redemande pas.")
        models = tk.Frame(inside, bg=self.colours.board)
        models.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 2))
        Button(models, self.says("reglages.telecharger_modeles"),
               self._offer_the_models, self.colours,
               width=300, height=32).pack(side="left")
        self.models_word = self._text(models, "", size=11, pale=True)
        self.models_word.pack(side="left", padx=(12, 0))
        rank += 1

        rank = self._block(inside, rank, "Rédaction du compte rendu",
                          "Qui rédige, avec quel modèle, et à qui le document part.")
        self.writer_setting = self._dropdown(inside, rank, "Rédacteur")
        rank += 1
        self.writing_model_setting = self._dropdown(inside, rank, "Modèle")
        rank += 1
        self.recipient_setting = self._entry(inside, rank, "Destinataire", 34)
        rank += 1

        rank = self._block(inside, rank, "Pendant la réunion",
                          "Le fil affiché en direct. Un second modèle tourne : c'est son coût.")
        self.live_active = tk.BooleanVar(value=self.config.live.active)
        self.case_direct = case = tk.Checkbutton(
            inside, text="Afficher ce qui se dit pendant la réunion",
            variable=self.live_active, bg=self.colours.board, fg=self.colours.ink,
            activebackground=self.colours.board, activeforeground=self.colours.ink,
            selectcolor=self.colours.ground, font=font(12), anchor="w",
            highlightthickness=0, borderwidth=0,
            disabledforeground=self.colours.calm, cursor="arrow",
        )
        case.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(1, 3))
        rank += 1
        self.period_setting = self._dropdown(inside, rank, "Tranche")
        rank += 1

        rank = self._block(
            inside, rank, "Assistant",
            "Le prénom auquel il répond pendant la réunion, et sa voix. "
            "Sa participation s'allume dans l'onglet En direct.")
        self.assistant_name_setting = self._dropdown(
            inside, rank, "Prénom", width=392)
        rank += 1
        self.assistant_voice_setting = self._dropdown(
            inside, rank, "Voix", width=392)
        rank += 1

        rank = self._block(inside, rank, "Apparence", "")
        self.theme_setting = self._dropdown(inside, rank, "Thème")
        rank += 1

        rank = self._block(inside, rank, "Version",
                          "Greffier lui-même, et ce qui est publié.")
        self.version_line = tk.Label(
            inside, text="", bg=self.colours.board, fg=self.colours.ink_pale,
            font=font(11), anchor="w", justify="left",
        )
        self.version_line.grid(row=rank, column=0, columnspan=2, sticky="w",
                               pady=(0, 6))
        rank += 1
        boutons_version = tk.Frame(inside, bg=self.colours.board)
        boutons_version.grid(row=rank, column=0, columnspan=2, sticky="w",
                             pady=(0, 2))
        self.update_greffier_button = Button(
            boutons_version, self.says("reglages.chercher_maj"),
            self._look_for_an_update, self.colours, width=210, height=32,
        )
        self.update_greffier_button.pack(side="left", padx=(0, 9))
        rank += 1
        self._text(
            inside, self.says("reglages.incidents", where=str(self.config.paths.troubles)),
            size=11, pale=True, wraplength=700, justify="left",
        ).grid(row=rank, column=0, columnspan=2, sticky="w", pady=(10, 0))
        rank += 1

        self._wire_the_settings()
        page.bind("<Map>", lambda _e: self._say_the_count())
        self.root.bind("<FocusIn>", self._on_return, add="+")
        self._listen_to_the_wheel(inside)
        self._fill_the_settings()
        self._say_the_count()
        self._say_the_version()

    def _on_return(self, _event: object = None) -> None:
        """Re-reads what may have changed while we were elsewhere."""
        if self.tabs.current == "Réglages":
            with contextlib.suppress(Exception):
                self._say_the_count()

    def _say_the_version(self) -> None:
        """Shows the installed version, asking the network nothing."""
        from greffier.adapters.updates import installed_version

        installed = installed_version()
        self.version_line.configure(
            text=f"Version {installed}." if installed
            else self.says("reglages.version_inconnue")
        )

    def _look_for_an_update(self) -> None:
        """Asks GitHub whether there is better. Installs nothing."""
        from greffier.adapters.updates import check

        self.update_greffier_button.activer(False)
        self.version_line.configure(text=self.says("reglages.verification"))

        def done(verdict: Any, trouble: Exception | None) -> None:
            self.update_greffier_button.activer(True)
            if trouble is not None:
                self.version_line.configure(text=f"Vérification impossible : {trouble}")
                return
            self.version_line.configure(text=verdict.say())
            if not verdict.update:
                return
            self._offer_the_install(verdict)

        self._run_job(Job(
            caption="mise à jour",
            do_it=lambda _say: check(),
            done=done,
        ))

    def _offer_the_install(self, verdict: Any) -> None:
        """Offers to install, by whichever way exists on this machine."""
        from greffier.adapters.updates import installable

        from_the_repository, because = installable()
        if from_the_repository:
            self._install_from_the_repository(verdict)
        elif verdict.downloadable:
            self._install_from_the_binary(verdict)
        else:
            self._paint_the_turn("greffier", (
                f"{verdict.say()} Rien à installer d'ici : {because}, et la "
                "version publiée ne porte pas d'archive pour ce système."
                + (f" À voir : {verdict.adresse}" if verdict.adresse else "")
            ))

    NOTHING_IS_LOST = (
        "Les réunions, les comptes rendus, la banque de voix, les "
        "conversations et les réglages ne sont pas touchés : ils vivent hors "
        "de l'application."
    )

    def _install_from_the_repository(self, verdict: Any) -> None:
        from greffier.adapters.updates import install

        if not asking.ask_yes_no(
            "Greffier",
            f"{verdict.say()}\n\nInstaller maintenant ? Greffier va se fermer, "
            f"se reconstruire depuis son dépôt, puis se relancer.\n\n"
            f"{self.NOTHING_IS_LOST}",
        ):
            return
        launched, where = install()
        if not launched:
            asking.complain("Greffier", f"Mise à jour impossible : {where}")
            return
        self._close_for_the_update()

    def _install_from_the_binary(self, verdict: Any) -> None:
        """Downloads the archive published for this system, then swaps the bundle."""
        import platform

        from greffier.adapters.updates import (
            install_from_release,
        )

        if not asking.ask_yes_no(
            "Greffier",
            f"{verdict.say()}\n\nTélécharger « {verdict.artefact_name} » et "
            "l'installer ? Greffier va se fermer puis se relancer sur la "
            "nouvelle version.\n\n"
            f"{self.NOTHING_IS_LOST}",
        ):
            return

        sur_mac = platform.system() == "Darwin"

        def do_it(say: Callable[[str], None]) -> Any:
            def progress(recu: int, total: int) -> None:
                if total:
                    say(f"téléchargement… {recu * 100 // total} %")
                else:
                    say(f"téléchargement… {recu // 1024 // 1024} Mo")

            return install_from_release(
                verdict, sys.executable, progress=progress
            )

        def done(outcome: Any, trouble: Exception | None) -> None:
            if trouble is not None:
                asking.complain("Greffier", f"Mise à jour impossible : {trouble}")
                return
            launched, where = outcome
            if not launched:
                asking.complain("Greffier", f"Mise à jour impossible : {where}")
                return
            if not sur_mac:
                self._paint_the_turn("greffier", (
                    f"La version {verdict.available} est téléchargée dans "
                    f"{where}. Ferme Greffier, remplace le dossier de "
                    f"l'application par celui-là, et relance. {self.NOTHING_IS_LOST}"
                ))
                return
            self._close_for_the_update()

        self._run_job(Job(caption="mise à jour", do_it=do_it, done=done))

    def _close_for_the_update(self) -> None:
        """The relay waits for this process to end before touching the bundle."""
        self.version_line.configure(text=self.says("reglages.maj_en_cours"))
        self.root.after(400, self.root.destroy)

    def _wire_the_settings(self) -> None:
        """Makes every change a save."""
        self.writer_setting.on_choice = lambda _key: self._chosen_writer()
        self.case_direct.configure(command=self._save_settings)
        self.recipient_setting.bind("<FocusOut>", lambda _e: self._save_settings())
        self.recipient_setting.bind("<Return>", lambda _e: self._save_settings())

    def _chosen_writer(self, _event: Any = None) -> None:
        """Changing writer changes the model list, then saves."""
        self._match_the_writer_model()
        self._save_settings()

    def _listen_to_the_wheel(self, parent: tk.Misc) -> None:
        for enfant in parent.winfo_children():
            if not isinstance(enfant, ttk.Combobox):
                enfant.bind("<MouseWheel>", self._settings_wheel)
            self._listen_to_the_wheel(enfant)

    def _scrolling_area(self, page: tk.Frame) -> tk.Frame:
        """A scrolling area, returning the frame to put content in."""
        c = self.colours
        page.rowconfigure(0, weight=0)   # la ligne d'état, en tête
        page.rowconfigure(1, weight=1)   # the scrolling area
        page.columnconfigure(0, weight=1)
        toile = tk.Canvas(page, bg=c.board, highlightthickness=0, borderwidth=0)
        toile.grid(row=1, column=0, sticky="nsew")
        scrollbar = Scroller(page, c, toile.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(6, 0))
        toile.configure(yscrollcommand=scrollbar.set)

        content = tk.Frame(toile, bg=c.board)
        window = toile.create_window((0, 0), window=content, anchor="nw")
        content.columnconfigure(1, weight=1)

        def to_content(_event: Any = None) -> None:
            toile.configure(scrollregion=toile.bbox("all"))

        def a_la_toile(event: Any) -> None:
            toile.itemconfigure(window, width=event.width)
            to_content()

        content.bind("<Configure>", to_content)
        toile.bind("<Configure>", a_la_toile)

        def wheel(event: Any) -> None:
            haut, bas = toile.yview()
            if haut <= 0.0 and bas >= 1.0:
                return
            step = -event.delta if platform.system() == "Darwin" else -event.delta // 120
            toile.yview_scroll(int(step), "units")

        for target in (toile, content):
            target.bind("<MouseWheel>", wheel)
        self._settings_wheel = wheel
        self.settings_canvas = toile
        self.settings_content = content
        return content

    def _block(self, parent: tk.Frame, rank: int, title: str, subtitle: str) -> int:
        """A block heading. Returns the next row, so as not to count by hand."""
        haut = 0 if rank == 0 else 13
        self._text(parent, title, size=12, gras=True).grid(
            row=rank, column=0, columnspan=2, sticky="w", pady=(haut, 1))
        if not subtitle:
            return rank + 1
        self._text(parent, subtitle, size=11, pale=True).grid(
            row=rank + 1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        return rank + 2

    def _dropdown(self, parent: tk.Frame, rank: int, caption: str,
                          width: int = 392) -> Listing:
        self._text(parent, caption, size=11, pale=True).grid(
            row=rank, column=0, sticky="w", padx=(0, 12), pady=3)
        listing = Listing(parent, self.colours, width=width,
                      on_choice=lambda _key: self._save_settings())
        listing.grid(row=rank, column=1, sticky="w", pady=3)
        return listing

    def _entry(self, parent: tk.Frame, rank: int, caption: str, width: int) -> tk.Entry:
        self._text(parent, caption, size=11, pale=True).grid(
            row=rank, column=0, sticky="w", padx=(0, 12), pady=2)
        field = self._field(parent, width)
        field.grid(row=rank, column=1, sticky="w", ipady=4, ipadx=4, pady=2)
        return field

    def _settable_first_names(self) -> list[tuple[str, str]]:
        """The tested first names, each with the gender of its voice."""
        from greffier.adapters.configuration import FIRST_NAMES, KINDS

        choice = [(first_name, f"{first_name} : {KINDS[speaker_index]}")
                 for first_name, speaker_index in FIRST_NAMES.items()]
        actuel = self.config.assistant.name
        if actuel and actuel not in FIRST_NAMES:
            choice.insert(0, (actuel, f"{actuel} : réglé à la main"))
        return choice

    def _settable_voices(self) -> list[tuple[str, str]]:
        """The voices offered, saying which one is installed."""
        from greffier.adapters.voice_neural import NeuralVoice

        installed = NeuralVoice(self.config.paths.synthetic_voice).installed
        return [
            ("kokoro", "Voix naturelle" if installed
             else "Voix naturelle (modèle absent, repli sur le système)"),
            ("systeme", "Voix du système"),
            ("aucun", "Aucune, il répond par écrit"),
        ]

    def _fill_the_settings(self) -> None:
        """Fills the form from the configuration in force."""
        from greffier.adapters.configuration import CLAUDE_MODELS

        self.microphone_setting.fill_menu(list(self._settable_mics()), self.config.audio.mic)
        self.model_setting.fill_menu(list(self._models_present()),
                                   self.config.transcription.model)
        self.language_setting.fill_menu(list(self.LANGUAGES), self.config.transcription.language)
        self.writer_setting.fill_menu(list(self.MOTEURS_REDACTION),
                                      self.config.minutes.engine)
        self._claude_models = tuple(CLAUDE_MODELS)
        self._match_the_writer_model()
        self.recipient_setting.delete(0, "end")
        self.recipient_setting.insert(0, self.config.minutes.recipient)
        self.period_setting.fill_menu(list(self.PERIODES_DIRECT),
                                    f"{self.config.live.period:.1f}")
        self.theme_setting.fill_menu(list(self.THEMES), self.config.appearance.theme)
        self.assistant_name_setting.fill_menu(self._settable_first_names(),
                                          self.config.assistant.name)
        self.assistant_voice_setting.fill_menu(self._settable_voices(),
                                           self.config.assistant.voice)
        people = self.config.speakers.people
        self.attendees_setting.fill_menu(list(self.ATTENDEES),
                                         str(people) if people else "")

    def _settable_mics(self) -> tuple[tuple[str, str], ...]:
        """The mics plugged in, plus automatic mode."""
        from greffier.wiring import list_

        names: list[str] = []
        try:
            hardware = list_(self.config).read()
        except (OSError, RuntimeError):
            hardware = None
        if hardware is not None:
            names = [p.name for p in hardware.mics
                    if not p.uid.startswith("com.reunions.")
                    and "blackhole" not in p.name.lower()]
        voulu = self.config.audio.mic
        if voulu and voulu not in names:
            names.append(f"{voulu}")
        return (("", self.says("fenetre.micro_automatique")),
                *((name, name) for name in names))

    def _models_present(self) -> tuple[tuple[str, str], ...]:
        """The transcription models this machine actually has.

        Looked for where the configured engine keeps them, which is the whole
        defect this fixes: it looked for whisper.cpp files only, so a machine
        transcribing perfectly well with faster-whisper -- whose models live in
        the Hugging Face cache -- was told « aucun modèle trouvé sur le disque »
        while it was using one.
        """
        from greffier.adapters.model_files import downloaded

        folder = self.config.paths.models

        def present(key: str) -> bool:
            if self.config.transcription.engine == "whisper.cpp":
                return (folder / f"ggml-{key}.bin").exists()
            return downloaded(key)

        present_line = tuple(
            (key, label_text) for key, label_text in self.TRANSCRIPTION_MODELS
            if present(key)
        )
        if present_line:
            return present_line
        return ((self.config.transcription.model,
                 f"{self.config.transcription.model}, "
                 "à télécharger au premier usage"),)

    def _match_the_writer_model(self) -> None:
        """The model list follows the chosen writer."""
        engine = self.writer_setting.value()
        if engine == "claude":
            choice = self._claude_models
        elif engine == "ollama":
            from greffier.adapters.writer_ollama import available_models

            present_line = available_models()
            choice = tuple((m, m) for m in present_line) or (
                ("qwen3:8b", "qwen3:8b, à télécharger"),
            )
        else:
            choice = (("", "Sans objet : aucun rédacteur"),)
        self.writing_model_setting.fill_menu(
            list(choice), self.config.minutes.model or (choice[0][0] if choice else ""))
        self.writing_model_setting.activer(engine != "aucun")

    def _say_the_count(self) -> None:
        """Shows the account state, and matches the buttons to it."""
        from greffier.adapters import system_diagnostic as diagnostic

        if not diagnostic.claude_installed():
            self.account_word.configure(
                text=self.says("reglages.claude_absent"),
                fg=self.colours.amber)
            self.session_button.set_caption("Installer")
            self.update_button.activer(False)
            return
        self.update_button.activer(True)
        count = diagnostic.claude_account()
        version = diagnostic.claude_version()
        if count is None:
            self.account_word.configure(
                text=f"Claude Code {version} : aucune session ouverte.",
                fg=self.colours.amber)
            self.session_button.set_caption("Se connecter")
            return
        formule = f" · {count.formule}" if count.formule else ""
        self.account_word.configure(text=f"Connecté · {count}{formule} · "
                                       f"Claude Code {version}",
                                  fg=self.colours.ink)
        self.session_button.set_caption("Changer de compte")

    def _claude_session(self) -> None:
        """Opens a terminal on `claude`, where the session is settled."""
        import tempfile

        from greffier.adapters import system_diagnostic as diagnostic

        if not diagnostic.claude_installed():
            command = diagnostic.CLAUDE_INSTALL_COMMAND.get(platform.system(), "")
            self.account_word.configure(text=f"À installer : {command}",
                                      fg=self.colours.amber)
            return
        if platform.system() != "Darwin":
            self.account_word.configure(
                text=self.says("reglages.ouvrir_claude"),
                fg=self.colours.amber)
            return
        already = diagnostic.claude_account() is not None
        appel = "claude /login" if already else "claude"
        script = Path(tempfile.gettempdir()) / "greffier-session-claude.command"
        script.write_text(
            "#!/bin/zsh -l\n"
            "echo 'Réglez votre session, puis revenez à Greffier : "
            "l'\\''état se relit tout seul.'\n"
            f"{appel}\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        subprocess.Popen(["open", str(script)])
        self.account_word.configure(
            text=self.says("reglages.terminal_ouvert"),
            fg=self.colours.ink_pale)
        self._watch_the_session(turns=60)

    def _watch_the_session(self, turns: int) -> None:
        """Re-reads the account every three seconds, while it is being settled."""
        from greffier.adapters import system_diagnostic as diagnostic

        def signature() -> tuple[str, str, str] | None:
            """What shows the account changed, without reading any token."""
            count = diagnostic.claude_account()
            if count is None:
                return None
            return (count.adresse, count.organisation, count.formule)

        avant = signature()

        def look(remaining: int) -> None:
            if remaining <= 0:
                return
            if signature() != avant:
                self._say_the_count()
                return
            self.root.after(3000, lambda: look(remaining - 1))

        self.root.after(3000, lambda: look(turns))

    def _update_claude(self) -> None:
        """Runs `claude update`, in a thread: it downloads."""
        from greffier.adapters import system_diagnostic as diagnostic

        if not diagnostic.claude_installed():
            self._say_the_count()
            return
        avant = diagnostic.claude_version()
        self.account_word.configure(text=f"Mise à jour depuis {avant}…",
                                  fg=self.colours.ink_pale)

        def do_it(_say: Callable[[str], None]) -> str:
            ran = subprocess.run(["claude", "update"], capture_output=True,
                                  text=True, check=False, timeout=600)
            output = (ran.stdout + ran.stderr).splitlines()
            lines = [line for line in output if line.strip()]
            return lines[-1][:120] if lines else ""

        def done(outcome: Any, trouble: Exception | None) -> None:
            if trouble is not None:
                self.account_word.configure(text=f"Mise à jour impossible : {trouble}",
                                          fg=self.colours.amber)
                return
            apres = diagnostic.claude_version()
            if apres and apres != avant:
                self.account_word.configure(text=f"Mis à jour : {avant} → {apres}",
                                          fg=self.colours.ink)
            else:
                self.account_word.configure(text=outcome or f"Déjà à jour ({avant}).",
                                          fg=self.colours.ink_pale)

        self._run_job(Job(caption="Mise à jour de Claude Code", do_it=do_it, done=done))

    def _apply_the_theme(self, theme: str, word: str = "") -> None:
        """Repaints the window without restarting it."""
        self.colours = palette(theme)
        self.root.configure(bg=self.colours.ground)
        self._style_the_lists()
        for enfant in self.root.winfo_children():
            enfant.destroy()
        self._phase_peinte = None
        self._known_microphones = ()
        self._thread_meeting = ""
        self._thread_position = 0
        self._construire()
        self.tabs.reveal("Réglages")
        if word:
            self.settings_word.configure(text=word)
        with contextlib.suppress(OSError, ValueError, tk.TclError):
            self._paint(self.recorder.read())

    def _save_settings(self) -> None:
        """Writes config.toml, then applies what can be applied at once."""
        from greffier.adapters import configuration as settings

        engine = self.writer_setting.value()
        theme_avant = self.config.appearance.theme
        neuf = self.config.model_copy(deep=True)
        neuf.audio.mic = self.microphone_setting.value()
        neuf.transcription.model = self.model_setting.value()
        neuf.transcription.language = self.language_setting.value()
        neuf.minutes.engine = engine
        neuf.minutes.model = ("" if engine == "aucun"
                                    else self.writing_model_setting.value())
        neuf.minutes.recipient = self.recipient_setting.get().strip()
        neuf.live.active = bool(self.live_active.get())
        neuf.live.period = float(self.period_setting.value())
        neuf.appearance.theme = self.theme_setting.value()
        from greffier.adapters.configuration import FIRST_NAMES

        neuf.assistant.name = (self.assistant_name_setting.value()
                              or self.config.assistant.name)
        neuf.assistant.speaker_index = FIRST_NAMES.get(neuf.assistant.name,
                                              self.config.assistant.speaker_index)
        neuf.assistant.voice = self.assistant_voice_setting.value()
        annonce = self.attendees_setting.value()
        neuf.speakers.people = int(annonce) if annonce else None

        try:
            settings.save_settings(neuf)
        except OSError as trouble:
            self.settings_word.configure(text=f"Échec de l'enregistrement : {trouble}")
            return

        self.config = neuf
        words = [f"Enregistré · {datetime.now().strftime('%H:%M:%S')}"]
        if neuf.minutes.engine == "claude":
            words.append(f"rédacteur {neuf.minutes.effective_model}")
        word = " · ".join(words)
        self.settings_word.configure(text=word)
        if neuf.appearance.theme != theme_avant:
            self.root.after(0, lambda: self._apply_the_theme(neuf.appearance.theme, word))

    def _load_mics(self) -> None:
        """Offers the mics actually plugged in, the configured one first."""
        from greffier.wiring import list_

        try:
            hardware = list_(self.config).read()
        except (OSError, RuntimeError):
            hardware = None
        names: list[str] = []
        if hardware is not None:
            names = [
                p.name for p in hardware.mics
                if not p.uid.startswith("com.reunions.")
                and "blackhole" not in p.name.lower()
            ]
        propositions = (("", self.says("fenetre.micro_automatique")),
                        *((name, name) for name in names))
        if propositions == self._known_microphones:
            return
        self._known_microphones = propositions
        chosen = self.mic.value()
        voulu = self.config.audio.mic
        known = [key for key, _ in propositions]
        kept = chosen if chosen in known else (voulu if voulu in known else "")
        self.mic.fill_menu(list(propositions), kept)

    def _refresh(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._paint(self.recorder.read())
        self._clear_messages()
        self.root.after(PERIOD_MS, self._refresh)

    def _follow_the_mics(self) -> None:
        """Keeps the mic list up to date, without reopening anything."""
        if self._phase_peinte in (None, Phase.REST):
            with contextlib.suppress(OSError, RuntimeError):
                self._load_mics()
        self.root.after(MICROPHONES_PERIOD_MS, self._follow_the_mics)

    def _breathe(self) -> None:
        """Pulses the red dot while recording."""
        if self._phase_peinte is Phase.RECORDING:
            c = self.colours
            part = (math.sin(2 * math.pi * time.time() / PULSATION_S) + 1) / 2
            self.badge.itemconfigure(self._point, fill=blend(c.active, c.board, part * 0.65))
        self.root.after(PULSATION_MS, self._breathe)

    def _paint(self, state: Any) -> None:
        c = self.colours
        if state.phase is not self._phase_peinte:
            precedente = self._phase_peinte
            self._phase_peinte = state.phase
            self._show_commands(state.phase)
            if state.phase is Phase.REST:
                self._load_mics()
            if state.phase is Phase.RECORDING and precedente is not None:
                self.tabs.reveal("En direct")

        active = state.phase is Phase.RECORDING
        en_pause = state.phase is Phase.PAUSE
        self._show_the_meters(active or en_pause)
        if not active:
            self.badge.itemconfigure(
                self._point, fill=c.amber if en_pause else c.calm
            )
        self.title.configure(text=state.name or self.says("fenetre.pret"))
        self.detail.configure(
            text=state.message or self.says("fenetre.aucun_enregistrement")
        )
        self.chrono.configure(text=clock(state.seconds) if active or en_pause else "")

        self._follow_the_live_thread(state)

        if active and state.chunks:
            self._paint_levels(read_level(state.chunks[-1]))
        else:
            self.seen_you.reveal(0)
            self.seen_others.reveal(0)
            self.who.configure(text="en pause" if en_pause else "",
                               fg=c.amber if en_pause else c.green)

    def _show_the_meters(self, wanted: bool) -> None:
        """Two meters of a microphone nobody is speaking into say nothing.

        Shown while a meeting runs, folded away the rest of the time: they took
        a fifth of every screen, including the ones where no recording is
        possible.
        """
        if getattr(self, "_meters_shown", None) == wanted:
            return
        self._meters_shown = wanted
        measures = getattr(self, "measures", None)
        if measures is None:
            return
        if wanted:
            measures.grid()
        else:
            measures.grid_remove()

    def _paint_levels(self, releve: LevelReading | None) -> None:
        if releve is None:
            self.who.configure(text="en attente du son…", fg=self.colours.ink_pale)
            return
        self.seen_you.reveal(releve.mic_share)
        self.seen_others.reveal(releve.systeme_part)
        self.who.configure(text=_VOICE_LABELS[releve.who], fg=self.colours.green)

    def _clear_messages(self) -> None:
        for job in list(self.jobs):
            while not job.messages.empty():
                self.status_line.configure(text=job.messages.get_nowait())

    def _start_recording(self) -> None:
        from greffier.adapters.companions import (
            start_the_live_thread,
            start_the_watch,
        )
        from greffier.cli import _prepare_capture

        chosen = self.mic.value()
        if chosen:
            self.config.audio.mic = chosen
        if not self._the_disk_can_hold_a_meeting():
            return
        try:
            precedente = _prepare_capture(self.config)
            self.recorder.start_recording("reunion", previous_output=precedente)
            start_the_watch(self.config.paths.data)
            start_the_live_thread(
                self.config.paths.data, self.config.live.active)
        except (RuntimeError, FileNotFoundError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        self._probe_the_send()

    def _the_disk_can_hold_a_meeting(self) -> bool:
        """Says what room is left, and asks before starting on almost none.

        A recording is the one piece nothing rebuilds. A disk filling up during
        a meeting leaves a clock going up on screen while nothing is written,
        and the loss is found afterwards.
        """
        import shutil

        from greffier.domain import space

        target = self.config.paths.recordings
        while not target.exists() and target.parent != target:
            target = target.parent
        try:
            libre = shutil.disk_usage(target).free
        except OSError:
            return True
        rest = space.Room(libre, channels=2 if platform.system() == "Darwin" else 1)
        said = space.said_in_french(rest)
        if not said:
            return True
        if rest.verdict is space.Verdict.TOO_LITTLE:
            return asking.ask_yes_no(
                "Greffier", f"{said}\n\nDémarrer quand même ?", default="no",
            )
        self.status_line.configure(text=said)
        return True

    def _probe_the_send(self) -> None:
        """Checks now that the minutes will be able to leave.

        Now and not at the end, and that is the whole point: a send failed at 12:17 in
        front of a locked screen, two hours after someone was at the keyboard.
        """
        from greffier.wiring import _sender

        if not self.config.minutes.recipient:
            return
        with contextlib.suppress(Exception):
            sender = _sender(self.config)
            sonde = getattr(sender, "eprouver", None)
            empeche = sonde() if callable(sonde) else None
            if empeche:
                self._say("note", f"Avant la fin de la réunion : {empeche}")

    def _pause(self) -> None:
        try:
            self.recorder.pause()
        except RuntimeError as trouble:
            asking.complain("Greffier", str(trouble))

    def _resume(self) -> None:
        try:
            self.recorder.resume()
        except RuntimeError as trouble:
            asking.complain("Greffier", str(trouble))

    def _close_window(self) -> None:
        """Closes the window : ending the meeting first, if there is one."""
        phase = None
        with contextlib.suppress(OSError, ValueError):
            phase = self.recorder.read().phase
        if phase in (Phase.RECORDING, Phase.PAUSE):
            if not asking.ask_yes_no(
                "Greffier",
                self.says("fenetre.quitter_pendant"),
            ):
                return
            from greffier.cli import _restore_the_output

            with contextlib.suppress(RuntimeError):
                state = self.recorder.stop_recording()
                _restore_the_output(state.previous_output)
        self.root.destroy()

    def _terminate(self) -> None:
        """Ends the meeting on screen at once, and waits afterwards.

        Stopping the encoder cleanly takes up to fifteen seconds, and it used to
        happen here, on the interface's own thread: the window froze on the
        click, painted nothing, and the only sign that the button had been
        pressed was that nothing happened. Reported twice in use.

        The click now paints the end, and everything that takes time -- closing
        the file, stitching the pieces, transcribing, naming, writing -- runs in
        the thread that already carries the chain.
        """
        self._paint_the_end()
        self._open_the_transcription()
        recording: dict[str, Any] = {}

        def stop_then_process(say: Callable[[str], None]) -> Any:
            from greffier.cli import _restore_the_output

            state = self.recorder.stop_recording()
            _restore_the_output(state.previous_output)
            if state.audio is None:
                return None
            recording["audio"] = state.audio
            return self._chain(
                state.audio, state.events, state.start, state.ended_at
            )(say)

        self._run_job(Job(
            caption="traitement",
            do_it=stop_then_process,
            done=lambda outcome, trouble: self._processing_done(
                recording.get("audio"), outcome, trouble
            ),
        ))

    def _open_the_transcription(self) -> None:
        """Opens the transcription model while the encoder is still closing.

        Measured: twelve to nineteen seconds to open large-v3, against seven to
        nine to transcribe forty seconds of meeting, and up to fifteen for the
        encoder to close its file. Paid at the same time as the closing, it is
        not paid afterwards, in front of somebody who is waiting.
        """
        def ouvrir() -> None:
            with contextlib.suppress(Exception):
                from greffier.wiring import _transcriber

                _transcriber(self.config).warm()

        threading.Thread(target=ouvrir, daemon=True).start()

    def _paint_the_end(self) -> None:
        """What the click shows before anything has actually stopped.

        Optimistic on purpose: the recorded state still says « recording » until
        the encoder has closed its file, and a quarter of a second later the
        refresh would overwrite this -- except that the state now carries the
        end as soon as the button is pressed, so the two agree.
        """
        self._phase_peinte = Phase.FINALISATION
        self._show_commands(Phase.FINALISATION)
        self.detail.configure(text=self.says("fenetre.fin_en_cours"))
        self.chrono.configure(text="")
        self.badge.itemconfigure(self._point, fill=self.colours.amber)
        self.seen_you.reveal(0)
        self.seen_others.reveal(0)
        self.who.configure(text="")
        self.root.update_idletasks()

    def _chain(
        self,
        audio: Path,
        events: list[str] | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> Callable[[Callable[[str], None]], Any]:
        """Prepares the chain's run, progress reported to the screen."""

        def do_it(say: Callable[[str], None]) -> Any:
            from greffier.wiring import recording, wire_up

            chain = wire_up(self.config)
            chain.log = recording(self.config).pour(audio.stem)
            publisher = chain.log

            def publish(phase: str, message: str = "") -> None:
                say(message or phase)
                if publisher is not None:
                    with contextlib.suppress(OSError, ValueError):
                        publisher.publish(phase, message)

            chain.log = type("Journal", (), {"publish": staticmethod(publish)})()
            return chain.run_chain(
                audio,
                send=bool(self.config.minutes.recipient),
                hardware_events=events,
                started_at=started_at,
                ended_at=ended_at,
            )

        return do_it

    def _processing_done(
        self, audio: Path | None, outcome: Any, trouble: Exception | None
    ) -> None:
        self._load_meetings()
        if trouble is not None:
            # No file: the recording never produced one -- an empty take, a
            # microphone refused. The chain has nothing to blame, so the reason
            # is shown plainly, as it was before the stop moved to the thread.
            if audio is None:
                asking.complain("Greffier", str(trouble))
                return
            self._processing_failed(audio, trouble)
            return
        if audio is None:
            return
        for warning in getattr(outcome, "warnings", []):
            self._say("note", warning)
        self.status_line.configure(text=self.says("reunions.compte_rendu_pret"))
        self._choose(audio.stem)
        self.tabs.reveal("Conversation")
        self._offer_what_comes_next(audio.stem, outcome)
        self._back_up_quietly()

    def _back_up_quietly(self) -> None:
        """Copies the data after a processed meeting, asking nothing."""
        if not self.config.backup.apres_chaque_reunion:
            return
        from greffier.application import back_up
        from greffier.locations import config_folder

        destination = (
            Path(self.config.backup.folder).expanduser()
            if self.config.backup.folder else self.config.paths.backups
        )
        try:
            faite = back_up.do_it(
                self.config.paths.data, config_folder(), destination,
                kept=self.config.backup.kept,
            )
        except (OSError, ValueError) as trouble:
            self._say("note", f"Sauvegarde impossible : {trouble}")
            return
        if faite.on_the_same_disk:
            self._say("note", (
                f"Données sauvegardées ({faite.bytes_read / 1024**2:.1f} Mo), mais sur "
                "le même disque : règle « sauvegarde.dossier » vers un disque "
                "externe ou un espace synchronisé pour être vraiment à l'abri."
            ))

    def _processing_failed(self, audio: Path, trouble: Exception) -> None:
        """Says what is left, and offers to resume where it stopped.

        Published and written **before** any dialog: the failure used to be reported
        only by a modal window and the note written only after the click. Locked
        screen, nobody to click, and the state stayed frozen on the phase under way.
        """
        self.status_line.configure(text=f"Échec : {trouble}")
        self.troubles.note("traitement", f"{type(trouble).__name__} : {trouble}")
        self._publish_the_failure(audio.stem, trouble)
        self._say("note", f"La rédaction de « {audio.stem} » a échoué : {trouble} "
                           "La transcription est gardée, « Rédiger » la reprend.")
        transcrite = False
        with contextlib.suppress(OSError, ValueError):
            transcrite = bool(self.store.read(audio.stem).utterances)
        if not transcrite:
            asking.complain("Greffier", str(trouble))
            return
        if asking.ask_yes_no(
            "Greffier",
            f"{trouble}\n\nLa transcription et les voix sont gardées : rien n'est "
            "perdu. Seule la rédaction a échoué.\n\nReprendre la rédaction "
            "maintenant ?",
        ):
            self._write_up_only(audio.stem)

    def _publish_the_failure(self, identifier: str, trouble: Exception) -> None:
        """Writes the failure into the meeting's state, for the other processes."""
        from greffier.wiring import recording

        with contextlib.suppress(Exception):
            log = recording(self.config).pour(identifier)
            if log is not None:
                log.publish(Phase.ECHEC.value, f"Échec : {trouble}")

    def _write_up_only(self, identifier: str) -> None:
        """Replays the writing only, without listening or transcribing again."""
        from greffier.application.render import regenerate_minutes
        from greffier.wiring import writer

        engine = writer(self.config)
        if engine is None:
            asking.tell("Greffier", self.says("reunions.aucun_redacteur"))
            return

        def do_it(say: Callable[[str], None]) -> Any:
            say("rédaction…")
            kept_one = self.store.read(identifier)
            text = regenerate_minutes(
                kept_one, engine, self.config.conversation.disclosure
            )
            target = self.config.paths.minutes_folder / f"{identifier}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return text

        def done(_outcome: Any, trouble: Exception | None) -> None:
            self._load_meetings()
            if trouble is not None:
                self.status_line.configure(text=f"Rédaction : {trouble}")
                self._say("note", f"La rédaction a encore échoué : {trouble}")
                return
            self.status_line.configure(text=self.says("reunions.compte_rendu_pret"))
            self._say("greffier", f"Le compte rendu de « {identifier} » est prêt.")

        self._run_job(Job(caption=f"rédaction de {identifier}",
                             do_it=do_it, done=done))

    def _offer_what_comes_next(self, identifier: str, outcome: Any) -> None:
        """What the tool asks of its own accord, once the minutes are ready."""
        self._say("greffier", f"Le compte rendu de « {identifier} » est prêt.")
        significant: dict[str, float] = getattr(outcome, "significant_voices", dict)()
        names: dict[str, str] = getattr(outcome, "names", {})
        unnamed = [voice for voice in significant if voice not in names]
        if unnamed:
            self._say(
                "greffier",
                f"{len(unnamed)} voix ne portent pas encore de nom. L'onglet Voix "
                "permet d'écouter dix secondes et de les nommer : elles seront "
                "reconnues seules aux réunions suivantes.",
            )
        recipient = self.config.minutes.recipient
        if recipient and getattr(outcome, "envoye", False):
            self._say("greffier", f"Envoyé à {recipient}.")
        elif recipient:
            self._say("greffier", f"L'envoi à {recipient} n'a pas abouti : "
                                   "onglet Réunions, « Envoyer par courriel ».")
        else:
            self._say("greffier", self.says("reunions.aucun_destinataire_long"))

    def _run_job(self, job: Job) -> None:
        self.jobs.append(job)
        self.status_line.configure(text=f"{job.caption} en cours…")

        def courir() -> None:
            outcome: Any = None
            trouble: Exception | None = None
            try:
                outcome = job.do_it(job.messages.put)
            except Exception as attrape:  # noqa: BLE001 - reported to the interface
                trouble = attrape
            self.root.after(0, lambda: self._finish(job, outcome, trouble))

        threading.Thread(target=courir, daemon=True).start()

    def _finish(self, job: Job, outcome: Any, trouble: Exception | None) -> None:
        if job in self.jobs:
            self.jobs.remove(job)
        if not self.jobs:
            self.status_line.configure(text="")
        job.done(outcome, trouble)

    def _selection(self) -> str | None:
        """The technical identifier of the chosen meeting."""
        choice = self.listing.selection()
        return str(choice[0]) if choice else None

    def _choose(self, identifier: str) -> None:
        """Selects a meeting, so the other tabs follow."""
        if self.listing.exists(identifier):
            self.listing.selection_set(identifier)
            self.listing.see(identifier)
            self._load_voices()

    def _load_meetings(self) -> None:
        from greffier.application.name_voice import voices_to_name

        kept = self._selection()
        for line in self.listing.get_children():
            self.listing.delete(line)
        for identifier in self.store.list_():
            try:
                detail = self.store.read(identifier)
            except (OSError, ValueError):
                continue
            minutes = self.config.paths.minutes_folder / f"{identifier}.md"
            self.listing.insert("", "end", iid=identifier, values=(
                readable_subject(identifier, minutes, detail.subject),
                len(voices_to_name(detail)),
                sum(len(r.text.split()) for r in detail.utterances),
                "oui" if minutes.exists() else "non",
            ))
        from greffier.domain import emptiness

        self._say_what_is_missing(
            emptiness.meetings(len(self.listing.get_children())),
            self.listing, self.meeting_guidance, self.meeting_buttons,
        )
        if kept:
            self._choose(kept)

    def _load_the_conversation(self) -> None:
        """Shows again what was already said about the chosen meeting."""
        from greffier.adapters import conversations_file

        identifier = self._thread_meeting or self._selection()
        if not identifier or identifier == self._shown_conversation:
            return
        self._shown_conversation = identifier
        turns = conversations_file.read(
            conversations_file.file_for(self.config.paths.conversations,
                                             identifier)
        )
        self._empty_out(self.thread)
        if not turns:
            self._paint_the_turn(
                "note",
                self.says("conversation.mode_emploi"),
            )
            return
        self._paint_the_turn("note", f"conversation de « {identifier} »")
        for turn in turns:
            self._paint_the_turn(turn.who, turn.text)

    def _load_voices(self) -> None:
        from greffier.application.name_voice import voices_to_name
        from greffier.domain import emptiness

        self._load_the_conversation()
        for line in self.voice.get_children():
            self.voice.delete(line)
        identifier = self._selection()
        if identifier is not None:
            try:
                detail = self.store.read(identifier)
            except (OSError, ValueError):
                detail = None
            for candidate in voices_to_name(detail) if detail else []:
                self.voice.insert("", "end", values=(
                    candidate.voice,
                    f"{candidate.duration / 60:.1f} min",
                    f"{candidate.part * 100:.0f} %",
                    candidate.name
                    or (f"≈ {candidate.proposition}" if candidate.proposition else "à nommer"),
                ))
        self._say_what_is_missing(
            emptiness.voices(identifier is not None, len(self.voice.get_children())),
            self.voice, self.voice_guidance, self.voice_buttons,
        )
        self._say_what_is_unsure(detail if identifier is not None else None)

    def _say_what_is_unsure(self, detail: Any) -> None:
        """Says how much of this meeting is worth listening to again.

        The model returns a certainty for every turn and the chain used to
        throw it away, so the minutes read the same whether the words were
        heard clearly or invented over a fan. Only said when it is worth
        saying: one doubtful turn in two hours is noise.
        """
        from greffier.domain import doubt

        if detail is None:
            return
        said = doubt.said_in_french(doubt.count(detail.utterances))
        if said:
            self.status_line.configure(text=said)

    def _process_selection(self) -> None:
        from greffier.adapters.audio_ffmpeg import why_unreadable

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        try:
            audio = self.store.read(identifier).audio
        except (OSError, ValueError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        # Before opening the models: a damaged file returned an exception from
        # the audio library, twenty seconds later, in a thread.
        empeche = why_unreadable(audio)
        if empeche:
            asking.complain("Greffier", empeche)
            return
        self._run_job(Job(
            caption=f"traitement de {identifier}",
            do_it=self._chain(audio),
            done=lambda outcome, trouble: self._processing_done(audio, outcome, trouble),
        ))

    def _write_up_selection(self) -> None:
        """Replays the writing of the chosen meeting, without transcribing."""
        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        self._write_up_only(identifier)

    def _drop_files(self) -> None:
        """Picks files, shows what it would do with them, then asks."""
        from greffier.application import publish as job
        from greffier.domain.store import offer, summarise

        choisis = asking.files_to_open(
            "Déposer des enregistrements, des vidéos ou des documents",
            parent=self.root,
        )
        if not choisis:
            return
        tools = job.tools_present()
        propositions = [
            offer(Path(path), Path(path).stat().st_size, tools)
            for path in choisis
        ]
        detail = "\n".join(
            f"  {p.destination:9} {p.file.name}"
            + (f"\n             ⚠ {p.blocked_by}" if p.blocked_by else "")
            for p in propositions
        )
        if not asking.ask_yes_no(
            "Greffier",
            f"{summarise(propositions)}\n\n{detail}\n\n"
            "Les sons et les vidéos deviennent des réunions à transcrire ; les "
            "documents servent à enrichir le contexte. Continuer ?",
        ):
            return

        document_writer = self._document_writer(propositions)

        def do_it(say: Callable[[str], None]) -> list:  # type: ignore[type-arg]
            faits = []
            for number, proposition in enumerate(propositions, start=1):
                say(f"{proposition.file.name} ({number}/{len(propositions)})…")
                faits.append(job.run_chain(
                    proposition, self.config.paths.recordings,
                    document_writer,
                ))
            return faits

        def done(faits: Any, trouble: Exception | None) -> None:
            self._load_meetings()
            if trouble is not None:
                self._say("note", f"Dépôt interrompu : {trouble}")
                return
            self._report_the_store(faits or [])

        self._run_job(Job(caption="dépôt", do_it=do_it, done=done))

    def _document_writer(self, propositions: list) -> Any:  # type: ignore[type-arg]
        """The writer in charge of reading the documents, if there is one."""
        from greffier.domain.store import Destination
        from greffier.wiring import cartographe

        if not any(p.destination is Destination.CONTEXT and p.feasible for p in propositions):
            return None
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.application.publish import CONSIGNES_DOCUMENT

        engine = cartographe(self.config)
        if isinstance(engine, ClaudeWriter):
            engine.own_guidance = CONSIGNES_DOCUMENT
        return engine

    def _report_the_store(self, faits: list) -> None:  # type: ignore[type-arg]
        """Says what the drop produced, and offers what it learned."""
        to_transcribe: list[str] = []
        appris: list[tuple[str, str, str]] = []
        for outcome in faits:
            if outcome.trouble:
                self._say("note",
                           f"{outcome.proposition.file.name} : {outcome.trouble}")
                continue
            if outcome.produit is not None:
                to_transcribe.append(outcome.produit.stem)
            appris.extend(outcome.appris)

        if to_transcribe:
            self._say("greffier", (
                f"{len(to_transcribe)} enregistrement(s) prêt(s) : "
                f"{', '.join(to_transcribe[:3])}"
                + ("…" if len(to_transcribe) > 3 else "")
                + self.says("reunions.aller_traiter")
            ))
        self._offer_to_the_context(appris)

    def _offer_to_the_context(self, appris: list) -> None:  # type: ignore[type-arg]
        """Shows what a document taught, and writes it if accepted."""
        from greffier.adapters import context_file

        if not appris:
            return
        detail = "\n".join(
            f"  {kind:8} {ecriture}" + (f", {sens}" if sens else "")
            for ecriture, sens, kind in appris
        )
        if not asking.ask_yes_no(
            "Greffier",
            f"{len(appris)} entrée(s) trouvée(s) dans les documents :\n\n"
            f"{detail}\n\nLes ajouter au contexte ?",
        ):
            self._say("note", self.says("conversation.rien_ajoute"))
            return
        poses = 0
        for ecriture, sens, kind in appris:
            ajout = (
                context_file.add_a_person if kind == "personne"
                else context_file.add_a_term
            )
            with contextlib.suppress(OSError):
                if ajout(self.config.paths.context, ecriture, sens):
                    poses += 1
        self._say("greffier", (
            f"{poses} entrée(s) ajoutée(s) au contexte, "
            f"{len(appris) - poses} déjà connue(s)."
            + (self.says("conversation.direct_ecrira_juste")
               if self._thread_meeting and poses else "")
        ))

    def _rename_selection(self) -> None:
        """Gives the chosen meeting a readable subject."""
        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        try:
            kept_one = self.store.read(identifier)
        except (OSError, ValueError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        from tkinter import simpledialog

        propose = simpledialog.askstring(
            self.says("reunions.renommer_titre"),
            self.says("reunions.sujet_demande"),
            initialvalue=kept_one.subject or readable_subject(
                identifier, self.config.paths.minutes_folder / f"{identifier}.md"
            ),
            parent=self.root,
        )
        if propose is None:
            return
        kept_one.subject = propose.strip()
        try:
            self.store.record(kept_one)
        except OSError as trouble:
            asking.complain("Greffier", str(trouble))
            return
        self._load_meetings()
        self.status_line.configure(
            text=f"Renommée : {kept_one.caption}" if kept_one.subject
            else self.says("reunions.sujet_efface")
        )

    def _forget_selection(self) -> None:
        """Erases a meeting, after saying exactly what goes."""
        from greffier.application import tidy

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        where = self._locations()
        pieces = tidy.pieces_de(where, identifier)
        if not pieces:
            asking.tell("Greffier", self.says("reunions.rien_a_effacer"))
            self._load_meetings()
            return
        detail = "\n".join(
            f"  {tidy.readable(p.bytes_read):>8}  {p.what}" for p in pieces
        )
        total = tidy.readable(sum(p.bytes_read for p in pieces))
        if not asking.ask_yes_no(
            "Greffier",
            f"Effacer définitivement « {identifier} » ?\n\n{detail}\n\n"
            f"{total} au total. L'enregistrement audio ne peut pas être refait.",
            default="no",
        ):
            return
        effacees = tidy.forget(where, identifier)
        self._load_meetings()
        self._load_voices()
        self.status_line.configure(
            text=f"{len(effacees)} fichier(s) effacé(s), "
                 f"{tidy.readable(sum(p.bytes_read for p in effacees))} libérés."
        )

    def _locations(self) -> Any:
        """Where a meeting's pieces live, according to the configuration."""
        from greffier.application.tidy import Places

        paths = self.config.paths
        return Places(
            meetings=paths.data / "reunions",
            recordings=paths.recordings,
            transcripts=paths.transcripts,
            minutes_folder=paths.minutes_folder,
            live=paths.live,
            propositions=paths.propositions,
            questions=paths.questions,
            conversations=paths.conversations,
            pieces=paths.pieces,
        )

    def _open_minutes(self) -> None:
        import subprocess

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        path = self.config.paths.minutes_folder / f"{identifier}.md"
        if not path.exists():
            asking.tell("Greffier", self.says("reunions.aucun_compte_rendu"))
            return
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, str(path)], check=False)

    def _send_selection(self) -> None:
        from greffier.wiring import _sender

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        path = self.config.paths.minutes_folder / f"{identifier}.md"
        if not path.exists():
            asking.tell("Greffier", self.says("reunions.traiter_d_abord"))
            return
        minutes = path.read_text(encoding="utf-8")
        objet = title(minutes, f"Compte rendu : {identifier}")
        target = self.config.minutes.recipient
        if not target:
            asking.tell(
                "Greffier",
                self.says("reunions.aucun_destinataire"),
            )
            return
        if not asking.ask_yes_no("Greffier", f"Envoyer à {target} ?\n\n{objet}"):
            return
        sender = _sender(self.config, require_recipient=False)
        if sender is None:
            asking.complain("Greffier", self.says("reunions.aucun_envoi"))
            return

        def do_it(say: Callable[[str], None]) -> Any:
            say(f"envoi à {target}…")
            sender.send(target, objet, minutes, [])
            return target

        self._run_job(Job(caption="envoi", do_it=do_it,
                             done=lambda _r, trouble: self._sending_done(target, trouble)))

    def _sending_done(self, target: str, trouble: Exception | None) -> None:
        if trouble is not None:
            asking.complain("Greffier", str(trouble))
            return
        self.status_line.configure(text=f"Envoyé à {target}")
        self._say("greffier", f"Compte rendu envoyé à {target}.")

    def _selected_voice(self) -> str | None:
        choice = self.voice.selection()
        return str(self.voice.item(choice[0], "values")[0]) if choice else None

    def _name_voice(self) -> None:
        from greffier.wiring import naming

        identifier, voice = self._selection(), self._selected_voice()
        name = self.name_field.get().strip()
        if not identifier:
            asking.tell("Greffier", self.says("voix.choisis_une_reunion"))
            return
        if not voice:
            asking.tell("Greffier", "Choisissez une voix dans la liste.")
            return
        if not name:
            asking.tell("Greffier", "Saisis un nom.")
            return
        acte = naming(self.config)
        try:
            acte.name_voice(identifier, voice, name)
        except (KeyError, RuntimeError, ValueError, OSError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        self.name_field.delete(0, "end")
        self._load_voices()
        self.status_line.configure(text=f"{name} est en banque.")
        self._say("greffier", f"{name} est en banque, et sera reconnue seule aux "
                               "prochaines réunions.")
        if acte.doute:
            self._say("greffier", acte.doute)
            asking.warn("Greffier", acte.doute)
        self._regenerate_after_naming(identifier)

    def _offer_the_models_once_seen(self, tries: int = 0) -> None:
        """Asks only over a window that is on screen, and never waits forever."""
        self.root.update_idletasks()
        if self.root.winfo_viewable() or tries >= PATIENCE_BEFORE_ASKING:
            self._offer_the_models()
            return
        self.root.after(100, lambda: self._offer_the_models_once_seen(tries + 1))

    def _offer_the_models(self) -> None:
        """Offers to fetch the models the machine is missing, and does it.

        The models live outside the application, so an update keeps them, and
        so a freshly downloaded application has none. Until now only the
        command-line installer knew how to fetch them, which meant
        double-clicking the published archive gave a tool that could not
        transcribe anything. That is not what an executable is for.
        """
        from greffier.adapters import model_files

        folder = self.config.paths.models
        missing = [
            m for m in model_files.missing(folder, self.config.transcription.engine)
            if m.required
        ]
        if not missing:
            if hasattr(self, "models_word"):
                self.models_word.configure(text=self.says("modeles.tous_en_place"))
            return
        if not asking.ask_yes_no(
            "Greffier",
            self.says("modeles.manquants", weight=model_files.weight(missing)),
        ):
            self._paint_the_turn("greffier", self.says("modeles.refuses"))
            return
        self._fetch_the_models(missing)

    def _fetch_the_models(self, missing: list[Any]) -> None:
        """Fetches the models in a thread, saying where it is.

        In a thread because this is one and a half gigabytes: a window frozen
        for ten minutes with nothing to read passes for broken.
        """
        from greffier.adapters import model_files

        folder = self.config.paths.models

        def do_it(say: Callable[[str], None]) -> Any:
            rates: list[str] = []
            for rang, model in enumerate(missing, start=1):
                def avancement(
                    recu: int, total: int, m: Any = model, n: int = rang
                ) -> None:
                    part = f"{recu * 100 // total} %" if total else f"{recu >> 20} Mo"
                    say(f"{m.role} ({n}/{len(missing)}) : {part}")

                pose, souci = model_files.fetch(model, folder, avancement)
                if not pose:
                    rates.append(f"{model.role} : {souci}")
            return rates

        def fini(rates: Any, souci: Exception | None) -> None:
            if souci is not None:
                self.troubles.note("modeles", f"{type(souci).__name__} : {souci}")
                asking.complain("Greffier", f"Téléchargement impossible : {souci}")
                return
            if rates:
                self.troubles.note("modeles", f"non téléchargés : {len(rates)}")
                self._paint_the_turn("greffier", (
                    self.says("modeles.echec_liste")
                    + "\n- ".join(rates)
                    + self.says("modeles.reessaie")
                ))
                return
            self._paint_the_turn("greffier", (
                self.says("modeles.pretes")
            ))
            self.status_line.configure(text=self.says("modeles.telecharges"))

        self._run_job(Job(caption="modèles", do_it=do_it, done=fini))

    def _report_a_newer_bundle(self) -> None:
        """Says when the running application is no longer the installed one."""
        from greffier.adapters.updates import bundle_is_newer

        if not bundle_is_newer():
            return
        self._say(
            "greffier",
            self.says("reglages.version_plus_recente"),
        )

    def _report_resumable_meetings(self) -> None:
        """Says whether a transcribed meeting is still waiting for its minutes."""
        from greffier.application.render import to_resume

        try:
            remaining = to_resume(self.store, self.config.paths.minutes_folder)
        except OSError:
            return
        if not remaining:
            return
        how_many = len(remaining)
        pluriel = "s" if how_many > 1 else ""
        self._say(
            "greffier",
            f"{how_many} réunion{pluriel} transcrite{pluriel} sans compte rendu : "
            f"{', '.join(remaining[:3])}"
            + (f" et {how_many - 3} autre{'s' if how_many > 4 else ''}"
               if how_many > 3 else "")
            + self.says("reunions.reprendre_la_redaction"),
        )

    def _split_the_voice(self) -> None:
        """Undoes the last join that produced the chosen voice.

        Naming two voices alike joins them, which is what one wants when the
        tool split one person in two. It was one click to do and nothing to
        undo, and two people joined by mistake stayed one until the minutes.
        """
        from greffier.wiring import naming

        identifier, voice = self._selection(), self._selected_voice()
        if not (identifier and voice):
            asking.tell("Greffier", self.says("voix.choisis_une_voix"))
            return
        try:
            naming(self.config).split(identifier, voice)
        except (KeyError, RuntimeError, ValueError, OSError) as souci:
            asking.complain("Greffier", str(souci))
            return
        self._load_voices()
        self.status_line.configure(
            text=f"La voix {voice} est séparée : les deux sont de nouveau distinctes."
        )
        self._regenerate_after_naming(identifier)

    def _forget_the_name(self) -> None:
        """Removes a voice's name, after confirmation."""
        from greffier.wiring import naming

        identifier, voice = self._selection(), self._selected_voice()
        if not (identifier and voice):
            asking.tell("Greffier", self.says("voix.choisis_une_voix"))
            return
        if not asking.ask_yes_no(
            "Greffier",
            f"Retirer le nom de la voix {voice} ?\n\n"
            "La réunion l'oublie. L'empreinte déjà versée en banque, elle, "
            "reste : « greffier connus » montre les entrées douteuses.",
        ):
            return
        try:
            naming(self.config).forget(identifier, voice)
        except (KeyError, RuntimeError, ValueError, OSError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        self._load_voices()
        self.status_line.configure(text=f"La voix {voice} n'a plus de nom.")

    def _export_selection(self) -> None:
        """Writes the transcript in a shape another tool can open.

        The format is not asked for in a box of its own: the save dialogue
        already asks for a name, and the extension chosen there says which of
        the three is wanted -- one gesture instead of two.
        """
        from greffier.domain import export as formats

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text=self.says("reunions.choisis_une_reunion"))
            return
        try:
            kept_one = self.store.read(identifier)
        except (OSError, ValueError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        if not kept_one.utterances:
            asking.tell("Greffier", "Cette réunion n'a pas encore été transcrite.")
            return
        target = asking.where_to_save(
            "Exporter la transcription",
            initialfile=f"{identifier}.srt",
            filetypes=(
                ("Sous-titres SRT", "*.srt"),
                ("Sous-titres WebVTT", "*.vtt"),
                ("Tableur CSV", "*.csv"),
            ),
            parent=self.root,
        )
        if not target:
            return
        path = Path(target)
        shape = path.suffix.lstrip(".").lower() or "srt"
        if shape not in formats.FORMATS:
            asking.complain("Greffier", f"« {path.suffix} » n'est pas un format "
                                         f"connu : {', '.join(formats.FORMATS)}.")
            return
        try:
            path.write_text(
                formats.rendered(shape, kept_one.utterances, kept_one.names),
                encoding="utf-8-sig" if shape == "csv" else "utf-8",
            )
        except OSError as trouble:
            asking.complain("Greffier", f"Écriture impossible : {trouble}")
            return
        self.status_line.configure(
            text=f"{path.name} écrit, {len(kept_one.utterances)} tour(s) de parole."
        )

    def _everywhere(self) -> Any:
        """Where a person can have been written down."""
        from greffier.application.erase_person import Everywhere

        paths = self.config.paths
        return Everywhere(
            meetings=paths.data / "reunions",
            minutes_folder=paths.minutes_folder,
            transcripts=paths.transcripts,
            live=paths.live,
            propositions=paths.propositions,
            questions=paths.questions,
            conversations=paths.conversations,
            preparations=paths.preparations,
            memory=paths.memory,
            troubles=paths.troubles,
        )

    def _person_aimed_at(self) -> str:
        """The first name typed, or the one the selected voice carries."""
        typed = self.name_field.get().strip()
        if typed:
            return typed
        chosen = self.voice.selection()
        if not chosen:
            return ""
        values = self.voice.item(chosen[0], "values")
        return str(values[3]).strip() if len(values) > 3 else ""

    def _forget_a_person(self) -> None:
        """Erases somebody from everything the tool kept of them.

        Removing the name from one voice leaves it in the minutes, the
        transcript, the thread and the memory. This is the other gesture, the
        one Article 17 asks for, and it says where the name stands before doing
        anything: a first name is a common word, and the same word meaning
        somebody else goes with it.
        """
        from greffier.adapters import graph_sqlite
        from greffier.adapters.voice_bank_files import FileVoiceBank
        from greffier.application import erase_person

        name = self._person_aimed_at()
        if not name:
            asking.tell("Greffier", "Tapez le prénom à effacer, ou choisissez "
                                     "une voix déjà nommée.")
            return
        where = self._everywhere()
        bank = FileVoiceBank(self.config.paths.voice_bank)
        person = bank.find(name)
        voiceprints = len(person.voiceprints) if person else 0
        traces = erase_person.inventory(where, name, voiceprints=voiceprints)
        if not traces:
            asking.tell("Greffier", f"« {name} » n'est écrit nulle part.")
            return

        detail = "\n".join(
            f"  {trace.occurrences:>4}  {trace.what}"
            + ("  (donnée biométrique)" if trace.biometric else "")
            for trace in traces
        )
        total = sum(trace.occurrences for trace in traces)
        if not asking.ask_yes_no(
            "Greffier",
            f"Effacer « {name} » partout ?\n\n{detail}\n\n"
            f"{total} occurrence(s). Les réunions restent : ce qui s'est décidé "
            "appartient à tous ceux qui étaient là. Le nom devient "
            "« Indéterminé », et cela ne se défait pas.",
            default="no",
        ):
            return
        done = erase_person.erase(
            where, name,
            forget_the_voiceprints=lambda who: self._forget_the_voiceprints(bank, who),
            forget_in_the_index=lambda who: (
                graph_sqlite.forget_person(self.config.paths.graph, who)
                if self.config.paths.graph.exists() else 0
            ),
        )
        self._load_meetings()
        self._load_voices()
        self.status_line.configure(
            text=f"« {name} » effacé : {done.occurrences} occurrence(s) dans "
                 f"{done.files} fichier(s)"
            + (f", {done.voiceprints} empreinte(s) vocale(s)"
               if done.voiceprints else "")
        )

    @staticmethod
    def _forget_the_voiceprints(bank: Any, name: str) -> int:
        """Erases somebody from the bank, and says how many prints went."""
        person = bank.find(name)
        how_many = len(person.voiceprints) if person else 0
        return how_many if bank.forget(name) else 0

    def _regenerate_after_naming(self, identifier: str) -> None:
        """Replays the writing, in a separate thread."""
        from greffier.application.render import regenerate_minutes
        from greffier.wiring import store, writer

        path = self.config.paths.minutes_folder / f"{identifier}.md"
        if not path.exists():
            return
        engine = writer(self.config)
        if engine is None:
            return

        def do_it(say: Callable[[str], None]) -> Any:
            say("rédaction…")
            meeting = store(self.config).read(identifier)
            return regenerate_minutes(
                meeting, engine, self.config.conversation.disclosure
            )

        self._run_job(Job(
            caption="régénération", do_it=do_it,
            done=lambda text, trouble: self._regeneration_done(path, text, trouble),
        ))

    def _regeneration_done(self, path: Path, text: Any, trouble: Exception | None) -> None:
        if trouble is not None:
            self._say("greffier", f"La régénération du compte rendu a échoué : {trouble}")
            return
        path.write_text(text, encoding="utf-8")
        self._say("greffier", self.says("reunions.regenere"))

    def _listen(self) -> None:
        import shutil
        import subprocess

        from greffier.application.name_voice import extract_audio, voices_to_name

        identifier, voice = self._selection(), self._selected_voice()
        if not (identifier and voice):
            asking.tell("Greffier", self.says("voix.choisis_une_voix"))
            return
        player = shutil.which("afplay") or shutil.which("aplay") or shutil.which("ffplay")
        if player is None:
            asking.tell("Greffier", "Aucun lecteur audio disponible.")
            return
        try:
            detail = self.store.read(identifier)
            candidate = next(c for c in voices_to_name(detail) if c.voice == voice)
            if candidate.excerpt is None:
                asking.tell("Greffier",
                                    "Aucun extrait exploitable pour cette voix.")
                return
            output = self.config.paths.data / "extraits" / f"{identifier}-{voice}.wav"
            excerpt = extract_audio(detail.audio, candidate.excerpt, output)
        except (StopIteration, RuntimeError, OSError, ValueError) as trouble:
            asking.complain("Greffier", str(trouble))
            return
        arguments = ([player, "-nodisp", "-autoexit", "-loglevel", "error", str(excerpt)]
                     if player.endswith("ffplay") else [player, str(excerpt)])
        subprocess.Popen(arguments)

    def _say(self, who: str, text: str) -> None:
        self._keep_the_turn(who, text)
        self._paint_the_turn(who, text)

    def _keep_the_turn(self, who: str, text: str) -> None:
        """Writes the turn under the meeting it is about, if there is one."""
        from greffier.adapters import conversations_file

        identifier = self._thread_meeting or self._selection()
        if not identifier:
            return
        conversations_file.add(
            conversations_file.file_for(self.config.paths.conversations,
                                             identifier),
            who, text,
        )

    def _paint_the_turn(self, who: str, text: str) -> None:
        self.thread.configure(state="normal")
        if who in ("moi", "greffier"):
            self.thread.insert("end", "TOI\n" if who == "moi" else "GREFFIER\n", "qui")
            self.thread.insert("end", f"{text}\n", "dit")
        else:
            self.thread.insert("end", f"{text}\n", "note")
        self.thread.see("end")
        self.thread.configure(state="disabled")

    def _clear_the_thread(self) -> None:
        """Empties the thread on screen. What was said stays in its meeting.

        Asked for on sight: it kept everything since the window opened, system
        notes and answers in one column, and nothing emptied it. A thread one
        cannot clear is a thread one stops reading.
        """
        self.thread.configure(state="normal")
        self.thread.delete("1.0", "end")
        self.thread.configure(state="disabled")
        self._paint_the_turn("note", self.says("conversation.vide"))

    def _answer_the_question(self, response: str) -> bool:
        """Treats the input as an answer to the question awaiting one."""
        from greffier.adapters import context_file, questions_file
        from greffier.domain.intents import agreement

        waiting = self._pending_questions[0]
        said = agreement(response)
        if said is True:
            retenu = waiting.question.expected
        elif said is False:
            retenu = ""
        elif len(response.split()) <= 3:
            retenu = response.strip()
        else:
            return False

        self.question.delete(0, "end")
        self._say("moi", response)
        file = questions_file.questions_file(
            self.config.paths.questions, self._thread_meeting
        )
        with contextlib.suppress(OSError):
            questions_file.answer(file, waiting.number, retenu or "non")
        if retenu:
            with contextlib.suppress(OSError):
                pose = context_file.add_a_term(
                    self.config.paths.context, retenu
                )
            self._say("note", (
                f"« {retenu} » ajouté au contexte : les prochaines réunions "
                "l'écriront juste." if pose
                else f"« {retenu} » était déjà connu."
            ))
        else:
            self._say("note", self.says("conversation.note_sans_suite"))
        self._pending_questions = self._pending_questions[1:]
        self._flag_the_unseen_questions()
        return True

    def _hear_an_intent(self, sentence: str) -> bool:
        """Recognises "remember that…" and asks for confirmation first."""
        from greffier.domain.intents import understand

        appris = understand(sentence)
        if appris is None:
            return False
        self._learning_pending = appris
        self.question.delete(0, "end")
        self._say("moi", sentence)
        self._say("note", appris.say())
        return True

    def _confirm_the_learning(self, response: str) -> bool:
        """Writes into the context when the answer confirms."""
        from greffier.adapters import context_file
        from greffier.domain.intents import What, agreement

        said = agreement(response)
        if said is None:
            self._learning_pending = None
            return False
        appris = self._learning_pending
        self._learning_pending = None
        self.question.delete(0, "end")
        self._say("moi", response)
        if not said:
            self._say("note", self.says("conversation.rien_ecrit"))
            return True

        ajout = (
            context_file.add_a_person if appris.what is What.NOBODY
            else context_file.add_a_term
        )
        pose = False
        with contextlib.suppress(OSError):
            pose = ajout(self.config.paths.context, appris.subject, appris.precision)
        if not pose:
            self._say("note", f"« {appris.subject} » était déjà dans le contexte.")
            return True
        self._say("greffier", (
            f"« {appris.subject} » ajouté au contexte. La transcription en cours "
            "l'écrira juste dès la prochaine tranche."
            if self._thread_meeting else
            f"« {appris.subject} » ajouté au contexte."
        ))
        return True

    def _with_the_documents(self, material: str, identifier: str) -> str:
        """Adds to the material the documents supplied, and the sources registered."""
        from greffier.adapters import attachments_file
        from greffier.wiring import company_sources

        documents = attachments_file.material(self.config.paths.pieces, identifier)
        if documents:
            material = (
                f"{material}\n\n--- Documents fournis pour cette réunion ---\n{documents}"
            )
        if self._sources is None:
            self._sources = company_sources(self.config)
        outside = self._sources.material()
        return f"{material}\n\n{outside}" if outside else material

    def _supply_a_document(self) -> None:
        """Hands the tool a document during the meeting, in one gesture."""
        from greffier.adapters import attachments_file
        from greffier.application import publish as job
        from greffier.domain.store import Destination, offer

        choisis = asking.files_to_open(
            "Fournir des documents pour cette réunion", parent=self.root,
        )
        if not choisis:
            return
        tools = job.tools_present()
        propositions = [
            offer(Path(path), Path(path).stat().st_size, tools)
            for path in choisis
        ]
        documents = [p for p in propositions if p.destination is Destination.CONTEXT]
        others = [p for p in propositions if p.destination is not Destination.CONTEXT]
        if others:
            self._say("note", (
                f"{len(others)} fichier(s) sont des sons ou des vidéos : ils "
                "deviennent des réunions à transcrire, pas du contexte. "
                "Onglet Réunions, « Déposer des fichiers »."
            ))
        if not documents:
            return

        identifier = self._thread_meeting or self._selection() or ""
        if not identifier:
            self._say("note", (
                self.says("conversation.document_sans_reunion")
            ))
        writer = self._document_writer(documents)

        def do_it(say: Callable[[str], None]) -> Any:
            kept: list[Any] = []
            appris: list[tuple[str, str, str]] = []
            troubles: list[str] = []
            for number, proposition in enumerate(documents, start=1):
                say(f"{proposition.file.name} ({number}/{len(documents)})…")
                read_ = job.read_the_text(proposition.file)
                if not read_.strip():
                    troubles.append(proposition.file.name)
                    continue
                if identifier:
                    piece = attachments_file.write(
                        self.config.paths.pieces, identifier,
                        proposition.file.name, read_,
                    )
                    if piece is not None:
                        kept.append(piece)
                if writer is not None:
                    appris.extend(job.learn_from_text(read_, writer))
            return (kept, appris, troubles)

        def done(rendered: Any, trouble: Exception | None) -> None:
            if trouble is not None:
                self._say("note", f"Lecture interrompue : {trouble}")
                return
            kept, appris, troubles = rendered
            for name in troubles:
                self._say("note", (
                    f"{name} : rien de lisible. Un PDF scanné demande "
                    "« pdftotext », et une image n'est pas du texte."
                ))
            for piece in kept:
                self._say("greffier", (
                    f"« {piece.name} » lu, {piece.caracteres} caractères gardés. "
                    "Vous pouvez me poser des questions dessus."
                ))
            self._offer_to_the_context(appris)

        self._run_job(Job(caption="lecture", do_it=do_it, done=done))

    # ---------------------------------------------- preparing a meeting

    def _preparations_folder(self) -> Path:
        return self.config.paths.preparations

    def _load_the_preparation(self) -> None:
        """Takes back the one waiting, so that closing the window loses nothing."""
        from greffier.adapters import preparations_file

        with contextlib.suppress(OSError, ValueError):
            self._preparation = preparations_file.waiting(self._preparations_folder())
        self._paint_the_preparation()

    def _paint_the_preparation(self) -> None:
        preparation = getattr(self, "_preparation", None)
        if not hasattr(self, "preparation_line"):
            return
        if preparation is None:
            self.preparation_line.configure(text="")
            self.prepare_button.set_caption(self.says("conversation.preparer"))
            return
        chunks = [self.says("conversation.en_preparation",
                                 subject=preparation.subject or "-")]
        if preparation.expected:
            chunks.append(f"attendus : {', '.join(preparation.expected)}")
        if preparation.to_raise:
            chunks.append(f"{len(preparation.to_raise)} point(s) à soulever")
        self.preparation_line.configure(text=" · ".join(chunks))
        self.prepare_button.set_caption(self.says("conversation.changer_de_sujet"))

    def _open_a_preparation(self) -> None:
        from tkinter import simpledialog

        from greffier.adapters import preparations_file

        subject = simpledialog.askstring(
            "Greffier", self.says("conversation.sujet_demande"), parent=self.root)
        if subject is None:
            return
        self._say_what_is_known(subject.strip())
        existante = getattr(self, "_preparation", None)
        if existante is not None:
            self._preparation = replace(existante, subject=subject.strip())
        else:
            self._preparation = preparations_file.open_one(
                self._preparations_folder(), subject)
        self._keep_the_preparation()
        self.tabs.reveal("Conversation")
        self._say("note", self.says("preparation.ouverte"))

    def _say_what_is_known(self, subject: str) -> None:
        """Opens the preparation on what earlier meetings on this subject left."""
        from greffier.wiring import known_about

        if not subject:
            return
        connu = known_about(self.config, subject)
        if connu:
            self._say_while_preparing("note", connu.strip())

    def _keep_the_preparation(self) -> None:
        from greffier.adapters import preparations_file

        preparation = getattr(self, "_preparation", None)
        if preparation is None:
            return
        with contextlib.suppress(OSError):
            preparations_file.write(self._preparations_folder(), preparation)
        self._paint_the_preparation()

    def _preparing(self) -> Any:
        """The use case, wired to this window's voice and cues."""
        from greffier.adapters.cue_sound import HEARD, cue
        from greffier.application.prepare import Preparing
        from greffier.wiring import (
            assistant,
            assistant_voice,
            context,
            known_about,
            what_earlier_meetings_left,
        )

        cerveau = assistant(self.config)
        if cerveau is None:
            return None
        voice = assistant_voice(self.config)
        preparation = getattr(self, "_preparation", None)
        return Preparing(
            brain=cerveau,
            setting=(context(self.config).header()
                     + what_earlier_meetings_left(self.config)),
            known=(known_about(self.config, preparation.subject)
                   if preparation is not None else ""),
            heard=cue(HEARD),
            speak=(voice.say if voice is not None else None),
        )

    def _open_the_voice(self) -> None:
        """Opens the voice and the ear while the person is still speaking.

        Measured: four and a half seconds to open the voice, then a third of a
        second per remark; and up to thirty-seven seconds to open the model that
        listens. Opened at the first question, both waits would fall on the one
        answer somebody is listening for.
        """
        def ouvrir() -> None:
            with contextlib.suppress(Exception):
                from greffier.wiring import assistant_voice, dictation_transcriber

                voice = assistant_voice(self.config)
                chauffer = getattr(voice, "warm", None)
                if callable(chauffer):
                    chauffer()
                listening = dictation_transcriber(self.config)
                if listening is not None:
                    listening.warm()

        threading.Thread(target=ouvrir, daemon=True).start()

    def _answer_while_preparing(self, question: str) -> None:
        """Asks, and keeps the exchange whatever comes back."""
        self._open_the_voice()
        preparing = self._preparing()
        if preparing is None:
            self._say_while_preparing(
                "note", self.says("commun.aucun_redacteur_configure"))
            return
        self._say_while_preparing("moi", question)

        def do_it(say: Callable[[str], None]) -> Any:
            say("réflexion…")
            return preparing.answer(self._preparation, question)

        def done(outcome: Any, trouble: Exception | None) -> None:
            if trouble is not None:
                self._say_while_preparing("note", str(trouble))
                return
            self._preparation, answered = outcome
            self._keep_the_preparation()
            self._say_while_preparing("greffier", answered)

        self._run_job(Job(caption="préparation", do_it=do_it, done=done))

    # ------------------------------------------------- speaking out loud

    PAS_DICTEE_MS = 200

    def _speak_or_stop(self) -> None:
        """One click to speak, one to stop -- and the silence stops it anyway.

        Holding a button down asked the person to hold a mouse while reading the
        very document they are asking about, which is what somebody preparing a
        meeting is doing. A click opens the microphone, the end of the sentence
        closes it, and a second click cuts it short.
        """
        if getattr(self, "_dictee", None) is not None:
            self._stop_dictating()
            return
        self._start_dictating()

    def _start_dictating(self) -> None:
        """Opens the microphone, and watches for the end of the sentence."""
        from greffier.adapters.dictation_ffmpeg import Dictation
        from greffier.domain.dictating import Take

        self._open_the_voice()

        dictee = Dictation(self.config.audio.mic or self.config.audio.input)
        file = self.config.paths.data / "dictee.wav"
        try:
            dictee.start(file)
        except OSError as trouble:
            self._say_while_preparing("note", str(trouble))
            return
        self._dictee = dictee
        self._take = Take()
        self._file_take = file
        self.speak_button.set_caption(self.says("conversation.je_ecoute"))
        self.root.after(self.PAS_DICTEE_MS, self._watch_the_dictation)

    def _watch_the_dictation(self) -> None:
        """Follows the level, and closes the take when the sentence is over."""
        from greffier.adapters.live_levels import read_level

        if getattr(self, "_dictee", None) is None:
            return
        with contextlib.suppress(OSError, ValueError):
            releve = read_level(self._file_take)
            if releve is not None:
                self._take.heard(releve.mic_db, self.PAS_DICTEE_MS / 1000)
        if self._take.over:
            self._stop_dictating()
            return
        self.root.after(self.PAS_DICTEE_MS, self._watch_the_dictation)

    def _stop_dictating(self) -> None:
        """Closes the microphone, transcribes what was said, and answers."""
        dictee = getattr(self, "_dictee", None)
        self._dictee = None
        self.speak_button.set_caption(self.says("conversation.parler"))
        if dictee is None:
            return
        file = dictee.stop()
        if file is None:
            self._say_while_preparing("note", self.says("conversation.rien_entendu"))
            return
        self._transcribe_and_ask(file)


    def _transcribe_and_ask(self, audio: Path) -> None:
        from greffier.wiring import dictation_transcriber

        transcripteur = dictation_transcriber(self.config)
        if transcripteur is None:
            self._say("note", self.says("modeles.aucun_transcripteur"))
            return
        preparing = self._preparing()

        def do_it(say: Callable[[str], None]) -> Any:
            say("j'écoute…")
            dites = transcripteur.transcribe(audio, self.config.transcription.language, "")
            return " ".join(u.text for u in dites)

        def done(said: Any, trouble: Exception | None) -> None:
            if trouble is not None:
                self._say("note", str(trouble))
                return
            question = (preparing.transcribed(str(said))
                        if preparing is not None else str(said).strip())
            if not question:
                self._say("note", self.says("conversation.rien_compris"))
                return
            self._ask_this(question)

        self._run_job(Job(caption="dictée", do_it=do_it, done=done))

    def _ask_this(self, question: str) -> None:
        """Routes a question, spoken or typed, to whoever should answer it."""
        if getattr(self, "_preparation", None) is not None:
            self._answer_while_preparing(question)
            return
        self.question.delete(0, "end")
        self.question.insert(0, question)
        self._ask()

    def _ask(self) -> None:
        from greffier.wiring import assistant

        question = self.question.get().strip()
        if not question:
            return
        if getattr(self, "_preparation", None) is not None:
            self.question.delete(0, "end")
            self._answer_while_preparing(question)
            return
        if self._pending_questions and self._answer_the_question(question):
            return
        if self._learning_pending is not None and self._confirm_the_learning(
            question
        ):
            return
        if self._hear_an_intent(question):
            return

        engine = assistant(self.config)
        if engine is None:
            self._say("note", self.says("commun.aucun_redacteur_configure"))
            return

        in_progress = self._thread.rendered() if self._thread_meeting else ""
        if in_progress:
            material, what, sur = in_progress, "la transcription en direct", self._thread_meeting
        else:
            identifier = self._selection()
            if identifier is None:
                self._say("note", self.says("conversation.choisis_ou_demarre"))
                return
            source = self.config.paths.minutes_folder / f"{identifier}.md"
            if not source.exists():
                self._say("note", f"« {identifier} » n'a pas encore de compte rendu. "
                                   "Onglet Réunions, « Traiter ».")
                return
            material, what, sur = source.read_text(encoding="utf-8"), "le compte rendu", identifier

        material = self._with_the_documents(material, sur)
        self.question.delete(0, "end")
        self._say("moi", question)

        def do_it(say: Callable[[str], None]) -> Any:
            say("réflexion…")
            return engine.write_up(
                f"Question : {question}\n\n"
                f"Ce qui a été dit : {what} de la réunion « {sur} » :\n{material}"
            )

        self._run_job(Job(
            caption="question",
            do_it=do_it,
            done=lambda response, trouble: self._say(
                "note" if trouble else "greffier", str(trouble) if trouble else str(response)
            ),
        ))

    def spin(self) -> None:
        # Taken back at startup: a preparation gathered yesterday evening must
        # still be there this morning, and closing a window is not giving up.
        self.root.after(300, self._load_the_preparation)
        self.root.after(600, self._report_missing_minutes)
        self.root.after(900, self._remind_of_the_disclosure)
        self.root.mainloop()

    def _remind_of_the_disclosure(self) -> None:
        """Reminds once per session that the attendees must be able to know."""
        from greffier.domain.consent import RAPPEL, read, to_draw

        if to_draw(read(self.config.conversation.disclosure)):
            self._paint_the_turn("greffier", RAPPEL)

    def _report_missing_minutes(self) -> None:
        """Says which meetings are still waiting for their minutes."""
        from greffier.domain.meeting import held_on

        with contextlib.suppress(OSError, ValueError):
            manquantes = [
                identifier
                for identifier in self.store.list_()[:20]
                if held_on(identifier) is not None
                and not (self.config.paths.minutes_folder / f"{identifier}.md").exists()
                and bool(self.store.read(identifier).utterances)
            ]
            if not manquantes:
                return
            pluriel = "s" if len(manquantes) > 1 else ""
            self._paint_the_turn("greffier", (
                f"{len(manquantes)} réunion{pluriel} transcrite{pluriel} sans compte "
                f"rendu : {', '.join(manquantes[:3])}"
                + ("…" if len(manquantes) > 3 else "")
                + self.says("reunions.rediger_sans_retranscrire")
            ))
            self.tabs.mark("Conversation", len(manquantes))

def open_it(config: Config) -> None:
    """The window's entry point."""
    Window(config).spin()
