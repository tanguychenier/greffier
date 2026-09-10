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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from greffier.adapters.configuration import Config
from greffier.adapters.live_levels import LevelReading, read_level
from greffier.application.follow import (
    GENRE_CORRECTION,
    GENRE_ETAT,
    GENRE_REUNION,
    ask,
    files,
    read_from,
    replay,
    request_a_split,
)
from greffier.domain.channels import WhoSpeaks
from greffier.domain.live import LiveThread, LiveTurn
from greffier.domain.minutes import title
from greffier.domain.models import Phase
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

PERIODE_MS = 250

PERIODE_MICROS_MS = 1000

PULSATION_MS = 50

PULSATION_S = 1.6

_LABEL_TEXT = 84

_NOMBRES = frozenset({"voix", "mots", "duree", "part"})

_LIBELLES_VOIX = {
    WhoSpeaks.PERSONNE: "",
    WhoSpeaks.TOI: "tu parles",
    WhoSpeaks.LES_AUTRES: "les autres parlent",
    WhoSpeaks.LES_DEUX: "vous parlez en même temps",
}

@dataclass
class Job:
    """A long task, carried by a thread, reporting back to the window."""

    caption: str
    do_it: Callable[[Callable[[str], None]], Any]
    done: Callable[[Any, Exception | None], None] = lambda _outcome, _trouble: None
    messages: queue.Queue[str] = field(default_factory=queue.Queue)

class Window:
    """Assembles the interface and keeps it up to date."""

    def __init__(self, config: Config) -> None:
        from greffier.wiring import recording, store

        self.config = config
        self.recorder = recording(config)
        self.store = store(config)
        self.colours = palette(config.appearance.theme)
        self.travaux: list[Job] = []
        self._phase_peinte: Phase | None = None
        self._micros_connus: tuple[tuple[str, str], ...] = ()
        self._thread = LiveThread()
        self._questions_vues: set[int] = set()
        self._questions_attente: list[Any] = []
        self._apprentissage_attente: Any = None
        self._shown_conversation = ""
        self._apprentissage: Any = None
        self._fil_reunion = ""
        self._fil_position = 0
        self._fil_annonce = ""
        self._menu: tk.Menu | None = None

        locate_tcl()
        self.racine = tk.Tk()
        self.racine.title("Greffier")
        with contextlib.suppress(tk.TclError):
            self.racine.tk.call("tk", "appname", "Greffier")
        self.racine.minsize(880, 660)
        self.racine.protocol("WM_DELETE_WINDOW", self._close_window)
        self.racine.geometry("880x660")
        self.racine.configure(bg=self.colours.ground)
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
                self.racine.option_add(option, value)

    def _text(self, parent: tk.Misc, content: str, taille: int = 13,
               gras: bool = False, pale: bool = False, **options: Any) -> tk.Label:
        return tk.Label(
            parent, text=content, bg=parent.cget("bg"), anchor="w",
            fg=self.colours.ink_pale if pale else self.colours.ink,
            font=font(taille, gras), **options,
        )

    def _champ(self, parent: tk.Misc, width: int | None = None) -> tk.Entry:
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
        self.racine.columnconfigure(0, weight=1)
        self.racine.rowconfigure(0, weight=1)
        corps = tk.Frame(self.racine, bg=c.ground)
        corps.grid(row=0, column=0, sticky="nsew", padx=24, pady=22)
        corps.columnconfigure(0, weight=1)
        corps.rowconfigure(1, weight=1)

        self._build_state(corps)
        self.tabs = Tabs(corps, c)
        self.tabs.grid(row=1, column=0, sticky="nsew", pady=(22, 0))
        self._meetings_tab()
        self._live_tab()
        self._voices_tab()
        self._conversation_tab()
        self._settings_tab()
        self.status_line = self._text(corps, "", taille=11, pale=True)
        self.status_line.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self._report_resumable_meetings()
        self._report_a_newer_bundle()

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
        self.pastille = tk.Canvas(line, width=12, height=12, highlightthickness=0,
                                  bg=c.board)
        self.pastille.grid(row=0, column=0, sticky="w", pady=(8, 0))
        self._point = self.pastille.create_oval(1, 1, 11, 11, fill=c.calm, outline="")
        self.title = self._text(line, "Prêt", taille=21, gras=True)
        self.title.configure(font=title_font(21))
        self.title.grid(row=0, column=1, sticky="w", padx=(11, 0))
        self.chrono = self._text(line, "", taille=27)
        self.chrono.grid(row=0, column=2, sticky="e")

        self.detail = self._text(inside, "Aucun enregistrement en cours.",
                                  taille=12, pale=True)
        self.detail.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        mesures = tk.Frame(inside, bg=c.board)
        mesures.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        mesures.columnconfigure(1, weight=1)
        self.vu_toi = self._ligne_vumetre(mesures, "Toi", 0)
        self.vu_autres = self._ligne_vumetre(mesures, "Les autres", 1)
        self.qui = self._text(mesures, "", taille=11, gras=True)
        self.qui.configure(fg=c.green)
        self.qui.grid(row=2, column=1, sticky="w", pady=(7, 0))

        self.commands = tk.Frame(inside, bg=c.board)
        self.commands.grid(row=3, column=0, sticky="ew", pady=(20, 0))
        self._build_commands()
        self._breathe()

    def _ligne_vumetre(self, parent: tk.Frame, caption: str, rank: int) -> LevelMeter:
        self._text(parent, caption, taille=11, pale=True).grid(
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
        Button(rest, "Démarrer la réunion", self._start_recording, c,
               principal=True, width=192, height=38).pack(side="left")
        self._text(rest, "Micro", taille=11, pale=True).pack(side="left", padx=(20, 8))
        self.mic = Listing(rest, c, width=286, height=36)
        self.mic.pack(side="left")
        self._load_mics()
        self.jeux[Phase.REST] = rest

        in_progress = tk.Frame(self.commands, bg=c.board)
        Button(in_progress, "Mettre en pause", self._pause, c,
               width=156, height=38).pack(side="left", padx=(0, 10))
        Button(in_progress, "Terminer la réunion", self._terminate, c,
               principal=True, width=192, height=38).pack(side="left")
        self.jeux[Phase.RECORDING] = in_progress

        pause = tk.Frame(self.commands, bg=c.board)
        Button(pause, "Reprendre", self._resume, c, principal=True,
               width=136, height=38).pack(side="left", padx=(0, 10))
        Button(pause, "Terminer la réunion", self._terminate, c,
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

    def _page(self, caption: str) -> tk.Frame:
        page = self.tabs.add(caption)
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

    def _meetings_tab(self) -> None:
        inside = self._page("Réunions")
        self.listing = self._listing(inside, (
            ("date", "Réunion", 320), ("voix", "Personnes", 90),
            ("mots", "Mots", 80), ("compte_rendu", "Compte rendu", 120),
        ))
        actions = ButtonBar(inside, self.colours)
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        for caption, action, width in (
            ("Traiter", self._process_selection, 100),
            ("Rédiger", self._write_up_selection, 100),
            ("Ouvrir", self._open_minutes, 96),
            ("Envoyer par courriel", self._send_selection, 180),
            ("Déposer…", self._drop_files, 116),
            ("Renommer", self._rename_selection, 110),
            ("Supprimer", self._forget_selection, 110),
            ("Rafraîchir", self._load_meetings, 116),
        ):
            actions.add(
                Button(actions, caption, action, self.colours,
                       width=width, height=34),
                width,
            )
        self.listing.bind("<<TreeviewSelect>>", lambda _e: self._load_voices())
        self._load_meetings()

    def _live_tab(self) -> None:
        """What is being said, while it is said — and correctable there."""
        c = self.colours
        inside = self._page("En direct")
        self.direct_etat = self._text(
            inside,
            "Le fil s'affiche ici pendant la réunion. Clique sur un nom pour "
            "corriger qui parle — un « ? » signale un nom deviné par la voix, "
            "pas encore confirmé.",
            taille=11, pale=True, wraplength=740, justify="left",
        )
        self.direct_etat.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        bar = tk.Frame(inside, bg=c.board)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.bouton_voix = Button(
            bar, self._voice_caption(), self._toggle_the_voice, self.colours,
            width=230, height=34,
            principal=self.config.assistant.voice != "aucun")
        self.bouton_voix.grid(row=0, column=0, sticky="w")
        self.bouton_initiative = Button(
            bar, self._initiative_caption(), self._toggle_initiative,
            self.colours, width=250, height=34,
            principal=self.config.assistant.initiative)
        self.bouton_initiative.grid(row=0, column=1, sticky="w", padx=(10, 0))
        Button(bar, "Fournir un document", self._supply_a_document,
               self.colours, width=190, height=34).grid(
                   row=0, column=2, sticky="w", padx=(10, 0))
        self.participation_line = self._text(
            inside, "", taille=11, pale=True, wraplength=740, justify="left")
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
        in a meeting — you press, it keeps talking, and the button looks broken.
        """
        from greffier.adapters import configuration as reglages
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
            reglages.save_settings(self.config)
        except OSError as trouble:
            self.config.assistant.voice = avant
            messagebox.showerror("Greffier", f"Réglage non enregistré : {trouble}")
            return
        self.bouton_voix.set_caption(self._voice_caption())
        self.bouton_voix.highlight(self.config.assistant.voice != "aucun")
        self._say_the_participation()
        if hasattr(self, "reglage_voix_assistant"):
            self.reglage_voix_assistant.choose(self.config.assistant.voice)

    def _initiative_caption(self) -> str:
        name = self.config.assistant.name
        return (f"{name} n'intervient que si on l'appelle"
                if self.config.assistant.initiative
                else f"Laisser {name} intervenir d'elle-même")

    def _toggle_initiative(self) -> None:
        """Lets it speak without being called, or takes that away."""
        from greffier.adapters import configuration as reglages

        avant = self.config.assistant.initiative
        self.config.assistant.initiative = not avant
        try:
            reglages.save_settings(self.config)
        except OSError as trouble:
            self.config.assistant.initiative = avant
            messagebox.showerror("Greffier", f"Réglage non enregistré : {trouble}")
            return
        self.bouton_initiative.set_caption(self._initiative_caption())
        self.bouton_initiative.highlight(self.config.assistant.initiative)
        self._say_the_participation()

    def _say_the_participation(self) -> None:
        """What the button just changed, in plain words."""
        name = self.config.assistant.name
        if self.config.assistant.voice == "aucun":
            mot = (f"{name} suit la réunion et pose ses questions dans l'onglet "
                   "Conversation : répondez-lui au clavier.")
        else:
            mot = (f"{name} peut prendre la parole. Appelez-la par son nom pour "
                   "lui poser une question.")
        mot += (" Elle peut aussi intervenir d'elle-même."
                if self.config.assistant.initiative
                else " Elle n'intervient jamais sans qu'on l'appelle.")
        self.participation_line.configure(text=mot)

    def _follow_the_live_thread(self, state: Any) -> None:
        """Reads what the listening process published since last time."""
        if state.identifier != self._fil_reunion:
            self._forget_the_live_thread(state.identifier)
        if not self._fil_reunion:
            return
        log, _ = files(self.config.paths.live, self._fil_reunion)
        lines, self._fil_position = read_from(log, self._fil_position)
        if not lines:
            return
        for line in lines:
            if line.get("genre") == GENRE_ETAT:
                self._fil_annonce = str(line.get("message", ""))
        deja = len(self._thread.turns)
        remaniement = {GENRE_CORRECTION, GENRE_REUNION}
        corrige = any(line.get("genre") in remaniement for line in lines)
        replay(lines, self._thread)
        if corrige:
            self._repaint_the_live_tab()
        else:
            self._ajouter_au_direct(self._thread.turns[deja:])
        self._say_the_live_state()
        self._follow_the_questions()

    def _follow_the_questions(self) -> None:
        """Shows what the tool is asking, and puts the count on the tab."""
        from greffier.adapters import questions_file

        if not self._fil_reunion:
            return
        file = questions_file.questions_file(
            self.config.paths.questions, self._fil_reunion
        )
        awaiting, _ = questions_file.read(file)
        for en_attente in awaiting:
            if en_attente.number in self._questions_vues:
                continue
            self._questions_vues.add(en_attente.number)
            self._say("note", f"❓ {en_attente.question.text}")
            self._say("note", "   Réponds « oui » ou « non » ci-dessous, ou "
                               "écris l'orthographe juste.")
        self._questions_attente = awaiting
        self.tabs.mark("Conversation", len(awaiting))

    def _forget_the_live_thread(self, identifier: str) -> None:
        """Starts over: another meeting, another thread."""
        self._thread = LiveThread()
        self._fil_reunion = identifier
        self._fil_position = 0
        self._fil_annonce = ""
        self._questions_vues = set()
        self._questions_attente = []
        self.tabs.mark("Conversation", 0)
        self._shown_conversation = ""
        self._load_the_conversation()
        self._empty_out(self.thread_widget)
        self._say_the_live_state()

    def _say_the_live_state(self) -> None:
        self.direct_etat.configure(
            text=live_state_line(
                en_reunion=bool(self._fil_reunion),
                annonce=self._fil_annonce,
                sentences=len(self._thread.turns),
            )
        )

    def _empty_out(self, zone: tk.Text) -> None:
        zone.configure(state="normal")
        zone.delete("1.0", "end")
        zone.configure(state="disabled")

    def _repaint_the_live_tab(self) -> None:
        self._empty_out(self.thread_widget)
        self._ajouter_au_direct(self._thread.turns)

    def _ajouter_au_direct(self, turns: list[LiveTurn]) -> None:
        if not turns:
            return
        suivait = self.thread_widget.yview()[1] > 0.999
        self.thread_widget.configure(state="normal")
        for turn in turns:
            self._ecrire_un_tour(turn)
        self.thread_widget.configure(state="disabled")
        if suivait:
            self.thread_widget.see("end")

    def _ecrire_un_tour(self, turn: LiveTurn) -> None:
        voice = self._thread.voice.get(turn.voice)
        firm = voice is not None and voice.certitude.firm
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
        menu = tk.Menu(self.racine, tearoff=0, font=font(12))
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
            phrase = tk.Menu(menu, tearoff=0, font=font(12))
            self._fill_menu(phrase, names, number, whole_voice=False)
            menu.add_cascade(label="Seulement cette phrase…", menu=phrase)
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
            "Greffier", "Qui parle ?", parent=self.racine
        )
        if name and name.strip():
            self._correct_the_live_thread(number, name.strip(), whole_voice)

    def _split_in_the_live_thread(self, identifier: str) -> None:
        """Undoes the last join that produced this voice."""
        defaite = self._thread.split(identifier)
        if defaite is None:
            messagebox.showinfo(
                "Greffier", "Cette voix n'a absorbé aucune autre voix."
            )
            return
        _, requests = files(self.config.paths.live, self._fil_reunion)
        try:
            request_a_split(requests, identifier)
        except OSError as trouble:
            messagebox.showerror(
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
            messagebox.showerror("Greffier", str(trouble))
            return
        _, requests = files(self.config.paths.live, self._fil_reunion)
        try:
            ask(requests, number, name, whole_voice)
        except OSError as trouble:
            messagebox.showerror(
                "Greffier",
                f"La correction est affichée mais n'a pas pu être transmise : {trouble}",
            )
        self._repaint_the_live_tab()

    def _voices_tab(self) -> None:
        inside = self._page("Voix")
        self._text(
            inside,
            "Nommer une voix la met en banque : elle sera reconnue seule aux réunions "
            "suivantes, sans qu'aucun prénom soit prononcé.",
            taille=11, pale=True, wraplength=740, justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.voice = self._listing(inside, (
            ("voix", "Voix", 100), ("duree", "Durée", 90),
            ("part", "Part", 80), ("nom", "Nom", 260),
        ), rank=1)

        entry = tk.Frame(inside, bg=self.colours.board)
        entry.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        self._text(entry, "Prénom", taille=11, pale=True).pack(
            side="left", padx=(0, 9)
        )
        self.champ_nom = self._champ(entry, width=20)
        self.champ_nom.pack(side="left", ipady=7, ipadx=5)
        self.champ_nom.bind("<Return>", lambda _e: self._name_voice())
        Button(entry, "Nommer", self._name_voice, self.colours, principal=True,
               width=110, height=34).pack(side="left", padx=(11, 9))
        Button(entry, "Écouter 10 s", self._listen, self.colours,
               width=140, height=34).pack(side="left")
        Button(entry, "Retirer le nom", self._forget_the_name, self.colours,
               width=150, height=34).pack(side="left", padx=(9, 0))
        Button(entry, "Séparer les deux voix", self._split_the_voice,
               self.colours, width=190, height=34).pack(side="left", padx=(9, 0))

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
        self.question = self._champ(entry)
        self.question.grid(row=0, column=0, sticky="ew", ipady=8, ipadx=5)
        self.question.bind("<Return>", lambda _e: self._ask())
        Button(entry, "Demander", self._ask, self.colours, principal=True,
               width=124, height=36).grid(row=0, column=1, padx=(11, 0))
        Button(entry, "Fournir un document", self._supply_a_document,
               self.colours, width=176, height=36).grid(
                   row=0, column=2, padx=(8, 0))
        self._paint_the_turn(
            "note",
            "Pose une question sur la réunion en cours, ou sur celle choisie dans "
            "l'onglet Réunions. Pendant une réunion, la réponse vient du fil du "
            "direct, et je peux chercher en ligne si la question sort de la réunion.",
        )
        self._paint_the_turn(
            "note",
            "Tu peux aussi m'apprendre quelque chose en une phrase — « retiens "
            "que FAST veut dire formulaire d'attestation » — ou me fournir un "
            "document : je réponds dessus et j'en propose le vocabulaire.",
        )

    MODELES_TRANSCRIPTION = (
        ("large-v3-turbo", "large-v3-turbo — le plus juste, conseillé"),
        ("large-v3", "large-v3 — plus lent, sans gain mesuré ici"),
        ("small", "small — rapide, pour les postes modestes"),
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
        ("claude", "Claude Code — la meilleure synthèse"),
        ("ollama", "Ollama — tout reste sur ce poste"),
        ("aucun", "Aucun — s'arrêter à la transcription"),
    )
    ATTENDEES = (("", "Déduit de l'enregistrement"),
                    *((str(n), f"{n} personnes") for n in range(2, 13)))
    PERIODES_DIRECT = (("5.0", "5 s — très réactif, plus de calcul"),
                       ("10.0", "10 s — conseillé"),
                       ("20.0", "20 s — économe, l'affichage suit de loin"))

    def _settings_tab(self) -> None:
        """The settings people actually change, without opening a file."""
        page = self._page("Réglages")
        header = tk.Frame(page, bg=self.colours.board)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        self.mot_reglages = self._text(
            header, "Chaque changement s'applique et s'enregistre aussitôt.",
            taille=11, pale=True)
        self.mot_reglages.grid(row=0, column=0, sticky="w")
        inside = self._scrolling_area(page)

        rank = 0
        rank = self._bloc(inside, rank, "Micro", "Celui que Greffier prend au démarrage.")
        self.reglage_micro = self._dropdown(inside, rank, "Appareil")
        rank += 1

        rank = self._bloc(inside, rank, "Participants",
                          "Le nombre de personnes autour de la table, si tu le connais.")
        self.reglage_participants = self._dropdown(inside, rank, "Personnes",
                                                          width=232)
        rank += 1

        rank = self._bloc(inside, rank, "Transcription",
                          "Le modèle de la transcription définitive, faite après la réunion.")
        self.reglage_modele = self._dropdown(inside, rank, "Modèle")
        rank += 1
        self.reglage_langue = self._dropdown(inside, rank, "Langue", width=232)
        rank += 1

        rank = self._bloc(inside, rank, "Compte Claude",
                          "C'est lui qui rédige : sans session ouverte, tout marche "
                          "sauf le compte rendu.")
        self.mot_compte = self._text(inside, "", taille=11)
        self.mot_compte.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 5))
        rank += 1
        buttons = tk.Frame(inside, bg=self.colours.board)
        buttons.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self.bouton_session = Button(buttons, "Se connecter", self._claude_session,
                                     self.colours, width=228, height=32)
        self.bouton_session.pack(side="left", padx=(0, 9))
        self.bouton_maj = Button(buttons, "Mettre à jour Claude Code",
                                 self._update_claude,
                                 self.colours, width=228, height=32)
        self.bouton_maj.pack(side="left")
        rank += 1

        rank = self._bloc(inside, rank, "Rédaction du compte rendu",
                          "Qui rédige, avec quel modèle, et à qui le document part.")
        self.reglage_redacteur = self._dropdown(inside, rank, "Rédacteur")
        rank += 1
        self.reglage_modele_redaction = self._dropdown(inside, rank, "Modèle")
        rank += 1
        self.reglage_destinataire = self._entry(inside, rank, "Destinataire", 34)
        rank += 1

        rank = self._bloc(inside, rank, "Pendant la réunion",
                          "Le fil affiché en direct. Un second modèle tourne : c'est son coût.")
        self.direct_actif = tk.BooleanVar(value=self.config.live.active)
        self.case_direct = case = tk.Checkbutton(
            inside, text="Afficher ce qui se dit pendant la réunion",
            variable=self.direct_actif, bg=self.colours.board, fg=self.colours.ink,
            activebackground=self.colours.board, activeforeground=self.colours.ink,
            selectcolor=self.colours.ground, font=font(12), anchor="w",
            highlightthickness=0, borderwidth=0,
            disabledforeground=self.colours.calm, cursor="arrow",
        )
        case.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(1, 3))
        rank += 1
        self.reglage_periode = self._dropdown(inside, rank, "Tranche")
        rank += 1

        rank = self._bloc(
            inside, rank, "Assistant",
            "Le prénom auquel il répond pendant la réunion, et sa voix. "
            "Sa participation s'allume dans l'onglet En direct.")
        self.reglage_nom_assistant = self._dropdown(
            inside, rank, "Prénom", width=392)
        rank += 1
        self.reglage_voix_assistant = self._dropdown(
            inside, rank, "Voix", width=392)
        rank += 1

        rank = self._bloc(inside, rank, "Apparence", "")
        self.reglage_theme = self._dropdown(inside, rank, "Thème")
        rank += 1

        rank = self._bloc(inside, rank, "Version",
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
        self.bouton_maj_greffier = Button(
            boutons_version, "Chercher une mise à jour",
            self._look_for_an_update, self.colours, width=210, height=32,
        )
        self.bouton_maj_greffier.pack(side="left", padx=(0, 9))
        rank += 1

        self._wire_the_settings()
        page.bind("<Map>", lambda _e: self._say_the_count())
        self.racine.bind("<FocusIn>", self._au_retour, add="+")
        self._listen_to_the_wheel(inside)
        self._fill_the_settings()
        self._say_the_count()
        self._say_the_version()

    def _au_retour(self, _event: object = None) -> None:
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
            else "Version inconnue : paquet installé sans métadonnées."
        )

    def _look_for_an_update(self) -> None:
        """Asks GitHub whether there is better. Installs nothing."""
        from greffier.adapters.updates import check

        self.bouton_maj_greffier.activer(False)
        self.version_line.configure(text="Vérification…")

        def done(verdict: Any, trouble: Exception | None) -> None:
            self.bouton_maj_greffier.activer(True)
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

        depuis_le_depot, because = installable()
        if depuis_le_depot:
            self._install_from_the_repository(verdict)
        elif verdict.downloadable:
            self._install_from_the_binary(verdict)
        else:
            self._paint_the_turn("greffier", (
                f"{verdict.say()} Rien à installer d'ici : {because}, et la "
                "version publiée ne porte pas d'archive pour ce système."
                + (f" À voir : {verdict.adresse}" if verdict.adresse else "")
            ))

    RIEN_N_EST_PERDU = (
        "Les réunions, les comptes rendus, la banque de voix, les "
        "conversations et les réglages ne sont pas touchés : ils vivent hors "
        "de l'application."
    )

    def _install_from_the_repository(self, verdict: Any) -> None:
        from greffier.adapters.updates import install

        if not messagebox.askyesno(
            "Greffier",
            f"{verdict.say()}\n\nInstaller maintenant ? Greffier va se fermer, "
            f"se reconstruire depuis son dépôt, puis se relancer.\n\n"
            f"{self.RIEN_N_EST_PERDU}",
        ):
            return
        launched, ou = install()
        if not launched:
            messagebox.showerror("Greffier", f"Mise à jour impossible : {ou}")
            return
        self._close_for_the_update()

    def _install_from_the_binary(self, verdict: Any) -> None:
        """Downloads the archive published for this system, then swaps the bundle."""
        import platform

        from greffier.adapters.updates import (
            install_from_release,
        )

        if not messagebox.askyesno(
            "Greffier",
            f"{verdict.say()}\n\nTélécharger « {verdict.artefact_nom} » et "
            "l'installer ? Greffier va se fermer puis se relancer sur la "
            "nouvelle version.\n\n"
            f"{self.RIEN_N_EST_PERDU}",
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
                messagebox.showerror("Greffier", f"Mise à jour impossible : {trouble}")
                return
            launched, ou = outcome
            if not launched:
                messagebox.showerror("Greffier", f"Mise à jour impossible : {ou}")
                return
            if not sur_mac:
                self._paint_the_turn("greffier", (
                    f"La version {verdict.available} est téléchargée dans "
                    f"{ou}. Ferme Greffier, remplace le dossier de "
                    f"l'application par celui-là, et relance. {self.RIEN_N_EST_PERDU}"
                ))
                return
            self._close_for_the_update()

        self._run_job(Job(caption="mise à jour", do_it=do_it, done=done))

    def _close_for_the_update(self) -> None:
        """The relay waits for this process to end before touching the bundle."""
        self.version_line.configure(text="Mise à jour en cours, fermeture…")
        self.racine.after(400, self.racine.destroy)

    def _wire_the_settings(self) -> None:
        """Makes every change a save."""
        self.reglage_redacteur.on_choice = lambda _key: self._chosen_writer()
        self.case_direct.configure(command=self._save_settings)
        self.reglage_destinataire.bind("<FocusOut>", lambda _e: self._save_settings())
        self.reglage_destinataire.bind("<Return>", lambda _e: self._save_settings())

    def _chosen_writer(self, _event: Any = None) -> None:
        """Changing writer changes the model list, then saves."""
        self._match_the_writer_model()
        self._save_settings()

    def _listen_to_the_wheel(self, parent: tk.Misc) -> None:
        for enfant in parent.winfo_children():
            if not isinstance(enfant, ttk.Combobox):
                enfant.bind("<MouseWheel>", self._molette_reglages)
            self._listen_to_the_wheel(enfant)

    def _scrolling_area(self, page: tk.Frame) -> tk.Frame:
        """A scrolling area, returning the frame to put content in."""
        c = self.colours
        page.rowconfigure(0, weight=0)   # la ligne d'état, en tête
        page.rowconfigure(1, weight=1)   # la zone qui défile
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
            pas = -event.delta if platform.system() == "Darwin" else -event.delta // 120
            toile.yview_scroll(int(pas), "units")

        for target in (toile, content):
            target.bind("<MouseWheel>", wheel)
        self._molette_reglages = wheel
        self.reglages_toile = toile
        self.reglages_contenu = content
        return content

    def _bloc(self, parent: tk.Frame, rank: int, title: str, sous_titre: str) -> int:
        """A block heading. Returns the next row, so as not to count by hand."""
        haut = 0 if rank == 0 else 13
        self._text(parent, title, taille=12, gras=True).grid(
            row=rank, column=0, columnspan=2, sticky="w", pady=(haut, 1))
        if not sous_titre:
            return rank + 1
        self._text(parent, sous_titre, taille=11, pale=True).grid(
            row=rank + 1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        return rank + 2

    def _dropdown(self, parent: tk.Frame, rank: int, caption: str,
                          width: int = 392) -> Listing:
        self._text(parent, caption, taille=11, pale=True).grid(
            row=rank, column=0, sticky="w", padx=(0, 12), pady=3)
        listing = Listing(parent, self.colours, width=width,
                      on_choice=lambda _key: self._save_settings())
        listing.grid(row=rank, column=1, sticky="w", pady=3)
        return listing

    def _entry(self, parent: tk.Frame, rank: int, caption: str, width: int) -> tk.Entry:
        self._text(parent, caption, taille=11, pale=True).grid(
            row=rank, column=0, sticky="w", padx=(0, 12), pady=2)
        champ = self._champ(parent, width)
        champ.grid(row=rank, column=1, sticky="w", ipady=4, ipadx=4, pady=2)
        return champ

    def _settable_first_names(self) -> list[tuple[str, str]]:
        """The tested first names, each with the gender of its voice."""
        from greffier.adapters.configuration import FIRST_NAMES, KINDS

        choix = [(first_name, f"{first_name} — {KINDS[speaker_index]}")
                 for first_name, speaker_index in FIRST_NAMES.items()]
        actuel = self.config.assistant.name
        if actuel and actuel not in FIRST_NAMES:
            choix.insert(0, (actuel, f"{actuel} — réglé à la main"))
        return choix

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
        from greffier.adapters.configuration import MODELES_CLAUDE

        self.reglage_micro.fill_menu(list(self._settable_mics()), self.config.audio.mic)
        self.reglage_modele.fill_menu(list(self._models_present()),
                                   self.config.transcription.model)
        self.reglage_langue.fill_menu(list(self.LANGUAGES), self.config.transcription.language)
        self.reglage_redacteur.fill_menu(list(self.MOTEURS_REDACTION),
                                      self.config.minutes.engine)
        self._modeles_claude = tuple(MODELES_CLAUDE)
        self._match_the_writer_model()
        self.reglage_destinataire.delete(0, "end")
        self.reglage_destinataire.insert(0, self.config.minutes.recipient)
        self.reglage_periode.fill_menu(list(self.PERIODES_DIRECT),
                                    f"{self.config.live.period:.1f}")
        self.reglage_theme.fill_menu(list(self.THEMES), self.config.appearance.theme)
        self.reglage_nom_assistant.fill_menu(self._settable_first_names(),
                                          self.config.assistant.name)
        self.reglage_voix_assistant.fill_menu(self._settable_voices(),
                                           self.config.assistant.voice)
        people = self.config.speakers.people
        self.reglage_participants.fill_menu(list(self.ATTENDEES),
                                         str(people) if people else "")

    def _settable_mics(self) -> tuple[tuple[str, str], ...]:
        """The mics plugged in, plus automatic mode."""
        from greffier.wiring import lister

        names: list[str] = []
        try:
            materiel = lister(self.config).read()
        except (OSError, RuntimeError):
            materiel = None
        if materiel is not None:
            names = [p.name for p in materiel.mics
                    if not p.uid.startswith("com.reunions.")
                    and "blackhole" not in p.name.lower()]
        voulu = self.config.audio.mic
        if voulu and voulu not in names:
            names.append(f"{voulu}")
        return (("", "Automatique — le mieux entendu"),
                *((name, name) for name in names))

    def _models_present(self) -> tuple[tuple[str, str], ...]:
        folder = self.config.paths.models
        present_line = tuple(
            (key, label_text) for key, label_text in self.MODELES_TRANSCRIPTION
            if (folder / f"ggml-{key}.bin").exists()
        )
        if present_line:
            return present_line
        return ((self.config.transcription.model,
                 f"{self.config.transcription.model} — aucun modèle trouvé sur le disque"),)

    def _match_the_writer_model(self) -> None:
        """The model list follows the chosen writer."""
        engine = self.reglage_redacteur.value()
        if engine == "claude":
            choix = self._modeles_claude
        elif engine == "ollama":
            from greffier.adapters.writer_ollama import available_models

            present_line = available_models()
            choix = tuple((m, m) for m in present_line) or (
                ("qwen3:8b", "qwen3:8b — à télécharger"),
            )
        else:
            choix = (("", "Sans objet : aucun rédacteur"),)
        self.reglage_modele_redaction.fill_menu(
            list(choix), self.config.minutes.model or (choix[0][0] if choix else ""))
        self.reglage_modele_redaction.activer(engine != "aucun")

    def _say_the_count(self) -> None:
        """Shows the account state, and matches the buttons to it."""
        from greffier.adapters import system_diagnostic as diagnostic

        if not diagnostic.claude_installed():
            self.mot_compte.configure(
                text="Claude Code n'est pas installé : aucun compte rendu ne pourra "
                     "être rédigé.",
                fg=self.colours.amber)
            self.bouton_session.set_caption("Installer")
            self.bouton_maj.activer(False)
            return
        self.bouton_maj.activer(True)
        count = diagnostic.claude_account()
        version = diagnostic.claude_version()
        if count is None:
            self.mot_compte.configure(
                text=f"Claude Code {version} — aucune session ouverte.",
                fg=self.colours.amber)
            self.bouton_session.set_caption("Se connecter")
            return
        formule = f" · {count.formule}" if count.formule else ""
        self.mot_compte.configure(text=f"Connecté · {count}{formule} · "
                                       f"Claude Code {version}",
                                  fg=self.colours.ink)
        self.bouton_session.set_caption("Changer de compte")

    def _claude_session(self) -> None:
        """Opens a terminal on `claude`, where the session is settled."""
        import tempfile

        from greffier.adapters import system_diagnostic as diagnostic

        if not diagnostic.claude_installed():
            command = diagnostic.COMMANDE_INSTALLER_CLAUDE.get(platform.system(), "")
            self.mot_compte.configure(text=f"À installer : {command}",
                                      fg=self.colours.amber)
            return
        if platform.system() != "Darwin":
            self.mot_compte.configure(
                text="Lance « claude » dans un terminal, puis reviens ici.",
                fg=self.colours.amber)
            return
        deja = diagnostic.claude_account() is not None
        appel = "claude /login" if deja else "claude"
        script = Path(tempfile.gettempdir()) / "greffier-session-claude.command"
        script.write_text(
            "#!/bin/zsh -l\n"
            "echo 'Règle ta session, puis reviens à Greffier : "
            "l'\\''état se relit tout seul.'\n"
            f"{appel}\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        subprocess.Popen(["open", str(script)])
        self.mot_compte.configure(
            text="Un terminal s'ouvre. Reviens ensuite ici : l'état se relit tout seul.",
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

        def look(restants: int) -> None:
            if restants <= 0:
                return
            if signature() != avant:
                self._say_the_count()
                return
            self.racine.after(3000, lambda: look(restants - 1))

        self.racine.after(3000, lambda: look(turns))

    def _update_claude(self) -> None:
        """Runs `claude update`, in a thread: it downloads."""
        from greffier.adapters import system_diagnostic as diagnostic

        if not diagnostic.claude_installed():
            self._say_the_count()
            return
        avant = diagnostic.claude_version()
        self.mot_compte.configure(text=f"Mise à jour depuis {avant}…",
                                  fg=self.colours.ink_pale)

        def do_it(_say: Callable[[str], None]) -> str:
            fait = subprocess.run(["claude", "update"], capture_output=True,
                                  text=True, check=False, timeout=600)
            output = (fait.stdout + fait.stderr).splitlines()
            lines = [line for line in output if line.strip()]
            return lines[-1][:120] if lines else ""

        def done(outcome: Any, trouble: Exception | None) -> None:
            if trouble is not None:
                self.mot_compte.configure(text=f"Mise à jour impossible : {trouble}",
                                          fg=self.colours.amber)
                return
            apres = diagnostic.claude_version()
            if apres and apres != avant:
                self.mot_compte.configure(text=f"Mis à jour : {avant} → {apres}",
                                          fg=self.colours.ink)
            else:
                self.mot_compte.configure(text=outcome or f"Déjà à jour ({avant}).",
                                          fg=self.colours.ink_pale)

        self._run_job(Job(caption="Mise à jour de Claude Code", do_it=do_it, done=done))

    def _apply_the_theme(self, theme: str, mot: str = "") -> None:
        """Repaints the window without restarting it."""
        self.colours = palette(theme)
        self.racine.configure(bg=self.colours.ground)
        self._style_the_lists()
        for enfant in self.racine.winfo_children():
            enfant.destroy()
        self._phase_peinte = None
        self._micros_connus = ()
        self._fil_reunion = ""
        self._fil_position = 0
        self._construire()
        self.tabs.reveal("Réglages")
        if mot:
            self.mot_reglages.configure(text=mot)
        with contextlib.suppress(OSError, ValueError, tk.TclError):
            self._paint(self.recorder.read())

    def _save_settings(self) -> None:
        """Writes config.toml, then applies what can be applied at once."""
        from greffier.adapters import configuration as reglages

        engine = self.reglage_redacteur.value()
        theme_avant = self.config.appearance.theme
        neuf = self.config.model_copy(deep=True)
        neuf.audio.mic = self.reglage_micro.value()
        neuf.transcription.model = self.reglage_modele.value()
        neuf.transcription.language = self.reglage_langue.value()
        neuf.minutes.engine = engine
        neuf.minutes.model = ("" if engine == "aucun"
                                    else self.reglage_modele_redaction.value())
        neuf.minutes.recipient = self.reglage_destinataire.get().strip()
        neuf.live.active = bool(self.direct_actif.get())
        neuf.live.period = float(self.reglage_periode.value())
        neuf.appearance.theme = self.reglage_theme.value()
        from greffier.adapters.configuration import FIRST_NAMES

        neuf.assistant.name = (self.reglage_nom_assistant.value()
                              or self.config.assistant.name)
        neuf.assistant.speaker_index = FIRST_NAMES.get(neuf.assistant.name,
                                              self.config.assistant.speaker_index)
        neuf.assistant.voice = self.reglage_voix_assistant.value()
        annonce = self.reglage_participants.value()
        neuf.speakers.people = int(annonce) if annonce else None

        try:
            reglages.save_settings(neuf)
        except OSError as trouble:
            self.mot_reglages.configure(text=f"Échec de l'enregistrement : {trouble}")
            return

        self.config = neuf
        words = [f"Enregistré · {datetime.now().strftime('%H:%M:%S')}"]
        if neuf.minutes.engine == "claude":
            words.append(f"rédacteur {neuf.minutes.effective_model}")
        mot = " · ".join(words)
        self.mot_reglages.configure(text=mot)
        if neuf.appearance.theme != theme_avant:
            self.racine.after(0, lambda: self._apply_the_theme(neuf.appearance.theme, mot))

    def _load_mics(self) -> None:
        """Offers the mics actually plugged in, the configured one first."""
        from greffier.wiring import lister

        try:
            materiel = lister(self.config).read()
        except (OSError, RuntimeError):
            materiel = None
        names: list[str] = []
        if materiel is not None:
            names = [
                p.name for p in materiel.mics
                if not p.uid.startswith("com.reunions.")
                and "blackhole" not in p.name.lower()
            ]
        propositions = (("", "Automatique — le mieux entendu"),
                        *((name, name) for name in names))
        if propositions == self._micros_connus:
            return
        self._micros_connus = propositions
        choisi = self.mic.value()
        voulu = self.config.audio.mic
        known = [key for key, _ in propositions]
        garde = choisi if choisi in known else (voulu if voulu in known else "")
        self.mic.fill_menu(list(propositions), garde)

    def _refresh(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._paint(self.recorder.read())
        self._clear_messages()
        self.racine.after(PERIODE_MS, self._refresh)

    def _follow_the_mics(self) -> None:
        """Keeps the mic list up to date, without reopening anything."""
        if self._phase_peinte in (None, Phase.REST):
            with contextlib.suppress(OSError, RuntimeError):
                self._load_mics()
        self.racine.after(PERIODE_MICROS_MS, self._follow_the_mics)

    def _breathe(self) -> None:
        """Pulses the red dot while recording."""
        if self._phase_peinte is Phase.RECORDING:
            c = self.colours
            part = (math.sin(2 * math.pi * time.time() / PULSATION_S) + 1) / 2
            self.pastille.itemconfigure(self._point, fill=blend(c.active, c.board, part * 0.65))
        self.racine.after(PULSATION_MS, self._breathe)

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
        if not active:
            self.pastille.itemconfigure(
                self._point, fill=c.amber if en_pause else c.calm
            )
        self.title.configure(text=state.name or "Prêt")
        self.detail.configure(text=state.message or "Aucun enregistrement en cours.")
        self.chrono.configure(text=clock(state.seconds) if active or en_pause else "")

        self._follow_the_live_thread(state)

        if active and state.chunks:
            self._paint_levels(read_level(state.chunks[-1]))
        else:
            self.vu_toi.reveal(0)
            self.vu_autres.reveal(0)
            self.qui.configure(text="en pause" if en_pause else "",
                               fg=c.amber if en_pause else c.green)

    def _paint_levels(self, releve: LevelReading | None) -> None:
        if releve is None:
            self.qui.configure(text="en attente du son…", fg=self.colours.ink_pale)
            return
        self.vu_toi.reveal(releve.micro_part)
        self.vu_autres.reveal(releve.systeme_part)
        self.qui.configure(text=_LIBELLES_VOIX[releve.qui], fg=self.colours.green)

    def _clear_messages(self) -> None:
        for job in list(self.travaux):
            while not job.messages.empty():
                self.status_line.configure(text=job.messages.get_nowait())

    def _start_recording(self) -> None:
        from greffier.cli import _lancer_direct, _lancer_veille, _prepare_capture

        choisi = self.mic.value()
        if choisi:
            self.config.audio.mic = choisi
        try:
            precedente = _prepare_capture(self.config)
            self.recorder.start_recording("reunion", sortie_precedente=precedente)
            _lancer_veille(self.config, None)
            _lancer_direct(self.config, None)
        except (RuntimeError, FileNotFoundError) as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        self._probe_the_send()

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
            messagebox.showerror("Greffier", str(trouble))

    def _resume(self) -> None:
        try:
            self.recorder.resume()
        except RuntimeError as trouble:
            messagebox.showerror("Greffier", str(trouble))

    def _close_window(self) -> None:
        """Closes the window — ending the meeting first, if there is one."""
        phase = None
        with contextlib.suppress(OSError, ValueError):
            phase = self.recorder.read().phase
        if phase in (Phase.RECORDING, Phase.PAUSE):
            if not messagebox.askyesno(
                "Greffier",
                "Une réunion est en cours d'enregistrement.\n"
                "La terminer proprement et quitter ?",
            ):
                return
            from greffier.cli import _restore_the_output

            with contextlib.suppress(RuntimeError):
                state = self.recorder.stop_recording()
                _restore_the_output(state.sortie_precedente)
        self.racine.destroy()

    def _terminate(self) -> None:
        from greffier.cli import _restore_the_output

        try:
            state = self.recorder.stop_recording()
        except RuntimeError as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        _restore_the_output(state.sortie_precedente)
        audio = state.audio
        if audio is None:
            return
        self._run_job(Job(
            caption="traitement",
            do_it=self._chaine(audio, state.events, state.start, state.terminee_le),
            done=lambda outcome, trouble: self._processing_done(audio, outcome, trouble),
        ))

    def _chaine(
        self,
        audio: Path,
        events: list[str] | None = None,
        commencee_le: datetime | None = None,
        terminee_le: datetime | None = None,
    ) -> Callable[[Callable[[str], None]], Any]:
        """Prepares the chain's run, progress reported to the screen."""

        def do_it(say: Callable[[str], None]) -> Any:
            from greffier.wiring import recording, wire_up

            chaine = wire_up(self.config)
            chaine.log = recording(self.config).pour(audio.stem)
            publisher = chaine.log

            def publish(phase: str, message: str = "") -> None:
                say(message or phase)
                if publisher is not None:
                    with contextlib.suppress(OSError, ValueError):
                        publisher.publish(phase, message)

            chaine.log = type("Journal", (), {"publish": staticmethod(publish)})()
            return chaine.run_chain(
                audio,
                send=bool(self.config.minutes.recipient),
                hardware_events=events,
                commencee_le=commencee_le,
                terminee_le=terminee_le,
            )

        return do_it

    def _processing_done(self, audio: Path, outcome: Any, trouble: Exception | None) -> None:
        self._load_meetings()
        if trouble is not None:
            self._processing_failed(audio, trouble)
            return
        for warning in getattr(outcome, "avertissements", []):
            self._say("note", warning)
        self.status_line.configure(text="Compte rendu prêt.")
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
        self._publish_the_failure(audio.stem, trouble)
        self._say("note", f"La rédaction de « {audio.stem} » a échoué : {trouble} "
                           "La transcription est gardée, « Rédiger » la reprend.")
        transcrite = False
        with contextlib.suppress(OSError, ValueError):
            transcrite = bool(self.store.read(audio.stem).utterances)
        if not transcrite:
            messagebox.showerror("Greffier", str(trouble))
            return
        if messagebox.askyesno(
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
            messagebox.showinfo("Greffier", "Aucun rédacteur configuré.")
            return

        def do_it(say: Callable[[str], None]) -> Any:
            say("rédaction…")
            gardee = self.store.read(identifier)
            text = regenerate_minutes(
                gardee, engine, self.config.conversation.disclosure
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
            self.status_line.configure(text="Compte rendu prêt.")
            self._say("greffier", f"Le compte rendu de « {identifier} » est prêt.")

        self._run_job(Job(caption=f"rédaction de {identifier}",
                             do_it=do_it, done=done))

    def _offer_what_comes_next(self, identifier: str, outcome: Any) -> None:
        """What the tool asks of its own accord, once the minutes are ready."""
        self._say("greffier", f"Le compte rendu de « {identifier} » est prêt.")
        significatives: dict[str, float] = getattr(outcome, "voix_significatives", dict)()
        names: dict[str, str] = getattr(outcome, "noms", {})
        sans_nom = [voice for voice in significatives if voice not in names]
        if sans_nom:
            self._say(
                "greffier",
                f"{len(sans_nom)} voix ne portent pas encore de nom. L'onglet Voix "
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
            self._say("greffier", "Aucun destinataire n'est configuré, le compte rendu "
                                   "reste sur le disque. Renseigne "
                                   "compte_rendu.destinataire pour qu'il puisse partir.")

    def _run_job(self, job: Job) -> None:
        self.travaux.append(job)
        self.status_line.configure(text=f"{job.caption} en cours…")

        def courir() -> None:
            outcome: Any = None
            trouble: Exception | None = None
            try:
                outcome = job.do_it(job.messages.put)
            except Exception as attrape:  # noqa: BLE001 - remonté à l'interface
                trouble = attrape
            self.racine.after(0, lambda: self._finish(job, outcome, trouble))

        threading.Thread(target=courir, daemon=True).start()

    def _finish(self, job: Job, outcome: Any, trouble: Exception | None) -> None:
        if job in self.travaux:
            self.travaux.remove(job)
        if not self.travaux:
            self.status_line.configure(text="")
        job.done(outcome, trouble)

    def _selection(self) -> str | None:
        """The technical identifier of the chosen meeting."""
        choix = self.listing.selection()
        return str(choix[0]) if choix else None

    def _choose(self, identifier: str) -> None:
        """Selects a meeting, so the other tabs follow."""
        if self.listing.exists(identifier):
            self.listing.selection_set(identifier)
            self.listing.see(identifier)
            self._load_voices()

    def _load_meetings(self) -> None:
        from greffier.application.name_voice import voices_to_name

        garde = self._selection()
        for line in self.listing.get_children():
            self.listing.delete(line)
        for identifier in self.store.lister():
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
        if garde:
            self._choose(garde)

    def _load_the_conversation(self) -> None:
        """Shows again what was already said about the chosen meeting."""
        from greffier.adapters import conversations_file

        identifier = self._fil_reunion or self._selection()
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
                "Pose une question sur la réunion en cours, ou sur celle choisie "
                "dans l'onglet Réunions. Pendant une réunion, la réponse vient du "
                "fil du direct, et je peux chercher en ligne si la question sort "
                "de la réunion.",
            )
            return
        self._paint_the_turn("note", f"— conversation de « {identifier} » —")
        for turn in turns:
            self._paint_the_turn(turn.qui, turn.text)

    def _load_voices(self) -> None:
        from greffier.application.name_voice import voices_to_name

        self._load_the_conversation()
        for line in self.voice.get_children():
            self.voice.delete(line)
        identifier = self._selection()
        if identifier is None:
            return
        try:
            detail = self.store.read(identifier)
        except (OSError, ValueError):
            return
        for candidate in voices_to_name(detail):
            self.voice.insert("", "end", values=(
                candidate.voice,
                f"{candidate.duration / 60:.1f} min",
                f"{candidate.part * 100:.0f} %",
                candidate.name
                or (f"≈ {candidate.proposition}" if candidate.proposition else "à nommer"),
            ))

    def _process_selection(self) -> None:
        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text="Choisis une réunion dans la liste.")
            return
        try:
            audio = self.store.read(identifier).audio
        except (OSError, ValueError) as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        self._run_job(Job(
            caption=f"traitement de {identifier}",
            do_it=self._chaine(audio),
            done=lambda outcome, trouble: self._processing_done(audio, outcome, trouble),
        ))

    def _write_up_selection(self) -> None:
        """Replays the writing of the chosen meeting, without transcribing."""
        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text="Choisis une réunion dans la liste.")
            return
        self._write_up_only(identifier)

    def _drop_files(self) -> None:
        """Picks files, shows what it would do with them, then asks."""
        from tkinter import filedialog

        from greffier.application import publish as job
        from greffier.domain.store import offer, summarise

        choisis = filedialog.askopenfilenames(
            parent=self.racine,
            title="Déposer des enregistrements, des vidéos ou des documents",
        )
        if not choisis:
            return
        outils = job.tools_present()
        propositions = [
            offer(Path(path), Path(path).stat().st_size, outils)
            for path in choisis
        ]
        detail = "\n".join(
            f"  {p.destin:9} {p.file.name}"
            + (f"\n             ⚠ {p.bloque_par}" if p.bloque_par else "")
            for p in propositions
        )
        if not messagebox.askyesno(
            "Greffier",
            f"{summarise(propositions)}\n\n{detail}\n\n"
            "Les sons et les vidéos deviennent des réunions à transcrire ; les "
            "documents servent à enrichir le contexte. Continuer ?",
        ):
            return

        redacteur_document = self._document_writer(propositions)

        def do_it(say: Callable[[str], None]) -> list:  # type: ignore[type-arg]
            faits = []
            for number, proposition in enumerate(propositions, start=1):
                say(f"{proposition.file.name} ({number}/{len(propositions)})…")
                faits.append(job.run_chain(
                    proposition, self.config.paths.recordings,
                    redacteur_document,
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

        if not any(p.destin is Destination.CONTEXT and p.feasible for p in propositions):
            return None
        from greffier.adapters.writer_claude import ClaudeWriter
        from greffier.application.publish import CONSIGNES_DOCUMENT

        engine = cartographe(self.config)
        if isinstance(engine, ClaudeWriter):
            engine.consignes_propres = CONSIGNES_DOCUMENT
        return engine

    def _report_the_store(self, faits: list) -> None:  # type: ignore[type-arg]
        """Says what the drop produced, and offers what it learned."""
        a_transcrire: list[str] = []
        appris: list[tuple[str, str, str]] = []
        for fait in faits:
            if fait.trouble:
                self._say("note",
                           f"{fait.proposition.file.name} : {fait.trouble}")
                continue
            if fait.produit is not None:
                a_transcrire.append(fait.produit.stem)
            appris.extend(fait.appris)

        if a_transcrire:
            self._say("greffier", (
                f"{len(a_transcrire)} enregistrement(s) prêt(s) : "
                f"{', '.join(a_transcrire[:3])}"
                + ("…" if len(a_transcrire) > 3 else "")
                + ". Onglet Réunions, « Traiter »."
            ))
        self._offer_to_the_context(appris)

    def _offer_to_the_context(self, appris: list) -> None:  # type: ignore[type-arg]
        """Shows what a document taught, and writes it if accepted."""
        from greffier.adapters import context_file

        if not appris:
            return
        detail = "\n".join(
            f"  {kind:8} {ecriture}" + (f" — {sens}" if sens else "")
            for ecriture, sens, kind in appris
        )
        if not messagebox.askyesno(
            "Greffier",
            f"{len(appris)} entrée(s) trouvée(s) dans les documents :\n\n"
            f"{detail}\n\nLes ajouter au contexte ?",
        ):
            self._say("note", "Rien n'a été ajouté au contexte.")
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
            + (" Le direct les écrira juste dès la prochaine tranche."
               if self._fil_reunion and poses else "")
        ))

    def _rename_selection(self) -> None:
        """Gives the chosen meeting a readable subject."""
        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text="Choisis une réunion dans la liste.")
            return
        try:
            gardee = self.store.read(identifier)
        except (OSError, ValueError) as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        from tkinter import simpledialog

        propose = simpledialog.askstring(
            "Renommer la réunion",
            "Sujet de la réunion :",
            initialvalue=gardee.subject or readable_subject(
                identifier, self.config.paths.minutes_folder / f"{identifier}.md"
            ),
            parent=self.racine,
        )
        if propose is None:
            return
        gardee.subject = propose.strip()
        try:
            self.store.record(gardee)
        except OSError as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        self._load_meetings()
        self.status_line.configure(
            text=f"Renommée : {gardee.caption}" if gardee.subject
            else "Sujet effacé : le titre du compte rendu reprend la main."
        )

    def _forget_selection(self) -> None:
        """Erases a meeting, after saying exactly what goes."""
        from greffier.application import tidy

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text="Choisis une réunion dans la liste.")
            return
        ou = self._locations()
        pieces = tidy.pieces_de(ou, identifier)
        if not pieces:
            messagebox.showinfo("Greffier", "Il ne reste rien à effacer pour cette réunion.")
            self._load_meetings()
            return
        detail = "\n".join(
            f"  {tidy.readable(p.bytes_read):>8}  {p.quoi}" for p in pieces
        )
        total = tidy.readable(sum(p.bytes_read for p in pieces))
        if not messagebox.askyesno(
            "Greffier",
            f"Effacer définitivement « {identifier} » ?\n\n{detail}\n\n"
            f"{total} au total. L'enregistrement audio ne peut pas être refait.",
            default="no",
        ):
            return
        effacees = tidy.forget(ou, identifier)
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
            self.status_line.configure(text="Choisis une réunion dans la liste.")
            return
        path = self.config.paths.minutes_folder / f"{identifier}.md"
        if not path.exists():
            messagebox.showinfo("Greffier", "Aucun compte rendu pour cette réunion.")
            return
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, str(path)], check=False)

    def _send_selection(self) -> None:
        from greffier.wiring import _sender

        identifier = self._selection()
        if identifier is None:
            self.status_line.configure(text="Choisis une réunion dans la liste.")
            return
        path = self.config.paths.minutes_folder / f"{identifier}.md"
        if not path.exists():
            messagebox.showinfo("Greffier", "Traite d'abord la réunion.")
            return
        minutes = path.read_text(encoding="utf-8")
        objet = title(minutes, f"Compte rendu : {identifier}")
        target = self.config.minutes.recipient
        if not target:
            messagebox.showinfo(
                "Greffier",
                "Aucun destinataire configuré. Renseigne compte_rendu.destinataire.",
            )
            return
        if not messagebox.askyesno("Greffier", f"Envoyer à {target} ?\n\n{objet}"):
            return
        sender = _sender(self.config, exiger_destinataire=False)
        if sender is None:
            messagebox.showerror("Greffier", "Aucun moyen d'envoi configuré.")
            return

        def do_it(say: Callable[[str], None]) -> Any:
            say(f"envoi à {target}…")
            sender.send(target, objet, minutes, [])
            return target

        self._run_job(Job(caption="envoi", do_it=do_it,
                             done=lambda _r, trouble: self._sending_done(target, trouble)))

    def _sending_done(self, target: str, trouble: Exception | None) -> None:
        if trouble is not None:
            messagebox.showerror("Greffier", str(trouble))
            return
        self.status_line.configure(text=f"Envoyé à {target}")
        self._say("greffier", f"Compte rendu envoyé à {target}.")

    def _selected_voice(self) -> str | None:
        choix = self.voice.selection()
        return str(self.voice.item(choix[0], "values")[0]) if choix else None

    def _name_voice(self) -> None:
        from greffier.wiring import naming

        identifier, voice = self._selection(), self._selected_voice()
        name = self.champ_nom.get().strip()
        if not identifier:
            messagebox.showinfo("Greffier", "Choisis une réunion dans l'onglet Réunions.")
            return
        if not voice:
            messagebox.showinfo("Greffier", "Choisis une voix dans la liste.")
            return
        if not name:
            messagebox.showinfo("Greffier", "Saisis un nom.")
            return
        acte = naming(self.config)
        try:
            acte.name_voice(identifier, voice, name)
        except (KeyError, RuntimeError, ValueError, OSError) as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        self.champ_nom.delete(0, "end")
        self._load_voices()
        self.status_line.configure(text=f"{name} est en banque.")
        self._say("greffier", f"{name} est en banque, et sera reconnue seule aux "
                               "prochaines réunions.")
        if acte.doute:
            self._say("greffier", acte.doute)
            messagebox.showwarning("Greffier", acte.doute)
        self._regenerate_after_naming(identifier)

    def _report_a_newer_bundle(self) -> None:
        """Says when the running application is no longer the installed one."""
        from greffier.adapters.updates import bundle_is_newer

        if not bundle_is_newer():
            return
        self._say(
            "greffier",
            "Une version plus récente de Greffier est installée, mais cette "
            "fenêtre tourne encore sur la précédente. Quitte l'application "
            "(⌘Q) et relance-la pour en profiter.",
        )

    def _report_resumable_meetings(self) -> None:
        """Says whether a transcribed meeting is still waiting for its minutes."""
        from greffier.application.render import to_resume

        try:
            restants = to_resume(self.store, self.config.paths.minutes_folder)
        except OSError:
            return
        if not restants:
            return
        combien = len(restants)
        pluriel = "s" if combien > 1 else ""
        self._say(
            "greffier",
            f"{combien} réunion{pluriel} transcrite{pluriel} sans compte rendu : "
            f"{', '.join(restants[:3])}"
            + (f" et {combien - 3} autre{'s' if combien > 4 else ''}"
               if combien > 3 else "")
            + ". Sélectionne-la dans Réunions et clique « Rédiger » : la "
            "transcription est gardée, seule la rédaction reste à refaire.",
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
            messagebox.showinfo("Greffier", "Choisis une réunion, puis une voix.")
            return
        try:
            naming(self.config).split(identifier, voice)
        except (KeyError, RuntimeError, ValueError, OSError) as souci:
            messagebox.showerror("Greffier", str(souci))
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
            messagebox.showinfo("Greffier", "Choisis une réunion, puis une voix.")
            return
        if not messagebox.askyesno(
            "Greffier",
            f"Retirer le nom de la voix {voice} ?\n\n"
            "La réunion l'oublie. L'empreinte déjà versée en banque, elle, "
            "reste : « greffier connus » montre les entrées douteuses.",
        ):
            return
        try:
            naming(self.config).forget(identifier, voice)
        except (KeyError, RuntimeError, ValueError, OSError) as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        self._load_voices()
        self.status_line.configure(text=f"La voix {voice} n'a plus de nom.")

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
        self._say("greffier", "Compte rendu régénéré avec les nouveaux noms.")

    def _listen(self) -> None:
        import shutil
        import subprocess

        from greffier.application.name_voice import extract_audio, voices_to_name

        identifier, voice = self._selection(), self._selected_voice()
        if not (identifier and voice):
            messagebox.showinfo("Greffier", "Choisis une réunion, puis une voix.")
            return
        player = shutil.which("afplay") or shutil.which("aplay") or shutil.which("ffplay")
        if player is None:
            messagebox.showinfo("Greffier", "Aucun lecteur audio disponible.")
            return
        try:
            detail = self.store.read(identifier)
            candidate = next(c for c in voices_to_name(detail) if c.voice == voice)
            if candidate.extrait is None:
                messagebox.showinfo("Greffier",
                                    "Aucun extrait exploitable pour cette voix.")
                return
            output = self.config.paths.data / "extraits" / f"{identifier}-{voice}.wav"
            extrait = extract_audio(detail.audio, candidate.extrait, output)
        except (StopIteration, RuntimeError, OSError, ValueError) as trouble:
            messagebox.showerror("Greffier", str(trouble))
            return
        arguments = ([player, "-nodisp", "-autoexit", "-loglevel", "error", str(extrait)]
                     if player.endswith("ffplay") else [player, str(extrait)])
        subprocess.Popen(arguments)

    def _say(self, qui: str, text: str) -> None:
        self._keep_the_turn(qui, text)
        self._paint_the_turn(qui, text)

    def _keep_the_turn(self, qui: str, text: str) -> None:
        """Writes the turn under the meeting it is about, if there is one."""
        from greffier.adapters import conversations_file

        identifier = self._fil_reunion or self._selection()
        if not identifier:
            return
        conversations_file.add(
            conversations_file.file_for(self.config.paths.conversations,
                                             identifier),
            qui, text,
        )

    def _paint_the_turn(self, qui: str, text: str) -> None:
        self.thread.configure(state="normal")
        if qui in ("moi", "greffier"):
            self.thread.insert("end", "TOI\n" if qui == "moi" else "GREFFIER\n", "qui")
            self.thread.insert("end", f"{text}\n", "dit")
        else:
            self.thread.insert("end", f"{text}\n", "note")
        self.thread.see("end")
        self.thread.configure(state="disabled")

    def _answer_the_question(self, response: str) -> bool:
        """Treats the input as an answer to the question awaiting one."""
        from greffier.adapters import context_file, questions_file
        from greffier.domain.intents import agreement

        en_attente = self._questions_attente[0]
        dit = agreement(response)
        if dit is True:
            retenu = en_attente.question.attendu
        elif dit is False:
            retenu = ""
        elif len(response.split()) <= 3:
            retenu = response.strip()
        else:
            return False

        self.question.delete(0, "end")
        self._say("moi", response)
        file = questions_file.questions_file(
            self.config.paths.questions, self._fil_reunion
        )
        with contextlib.suppress(OSError):
            questions_file.answer(file, en_attente.number, retenu or "non")
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
            self._say("note", "Noté, je ne redemanderai pas.")
        self._questions_attente = self._questions_attente[1:]
        self.tabs.mark("Conversation", len(self._questions_attente))
        return True

    def _hear_an_intent(self, phrase: str) -> bool:
        """Recognises "remember that…" and asks for confirmation first."""
        from greffier.domain.intents import understand

        appris = understand(phrase)
        if appris is None:
            return False
        self._apprentissage_attente = appris
        self.question.delete(0, "end")
        self._say("moi", phrase)
        self._say("note", appris.say())
        return True

    def _confirm_the_learning(self, response: str) -> bool:
        """Writes into the context when the answer confirms."""
        from greffier.adapters import context_file
        from greffier.domain.intents import What, agreement

        dit = agreement(response)
        if dit is None:
            self._apprentissage_attente = None
            return False
        appris = self._apprentissage_attente
        self._apprentissage_attente = None
        self.question.delete(0, "end")
        self._say("moi", response)
        if not dit:
            self._say("note", "Rien n'a été écrit.")
            return True

        ajout = (
            context_file.add_a_person if appris.quoi is What.PERSONNE
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
            if self._fil_reunion else
            f"« {appris.subject} » ajouté au contexte."
        ))
        return True

    def _with_the_documents(self, material: str, identifier: str) -> str:
        """Adds to the material the text of the documents supplied."""
        from greffier.adapters import attachments_file

        documents = attachments_file.material(self.config.paths.pieces, identifier)
        if not documents:
            return material
        return (
            f"{material}\n\n--- Documents fournis pour cette réunion ---\n{documents}"
        )

    def _supply_a_document(self) -> None:
        """Hands the tool a document during the meeting, in one gesture."""
        from tkinter import filedialog

        from greffier.adapters import attachments_file
        from greffier.application import publish as job
        from greffier.domain.store import Destination, offer

        choisis = filedialog.askopenfilenames(
            parent=self.racine,
            title="Fournir des documents pour cette réunion",
        )
        if not choisis:
            return
        outils = job.tools_present()
        propositions = [
            offer(Path(path), Path(path).stat().st_size, outils)
            for path in choisis
        ]
        documents = [p for p in propositions if p.destin is Destination.CONTEXT]
        autres = [p for p in propositions if p.destin is not Destination.CONTEXT]
        if autres:
            self._say("note", (
                f"{len(autres)} fichier(s) sont des sons ou des vidéos : ils "
                "deviennent des réunions à transcrire, pas du contexte. "
                "Onglet Réunions, « Déposer des fichiers »."
            ))
        if not documents:
            return

        identifier = self._fil_reunion or self._selection() or ""
        if not identifier:
            self._say("note", (
                "Aucune réunion en cours ni choisie : je lis quand même les "
                "documents pour en tirer du vocabulaire, mais leur texte ne "
                "sera rangé sous aucune réunion."
            ))
        writer = self._document_writer(documents)

        def do_it(say: Callable[[str], None]) -> Any:
            kept: list[Any] = []
            appris: list[tuple[str, str, str]] = []
            troubles: list[str] = []
            for number, proposition in enumerate(documents, start=1):
                say(f"{proposition.file.name} ({number}/{len(documents)})…")
                lu = job.lire_le_texte(proposition.file)
                if not lu.strip():
                    troubles.append(proposition.file.name)
                    continue
                if identifier:
                    piece = attachments_file.write(
                        self.config.paths.pieces, identifier,
                        proposition.file.name, lu,
                    )
                    if piece is not None:
                        kept.append(piece)
                if writer is not None:
                    appris.extend(job.learn_from_text(lu, writer))
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
                    "Tu peux me poser des questions dessus."
                ))
            self._offer_to_the_context(appris)

        self._run_job(Job(caption="lecture", do_it=do_it, done=done))

    def _ask(self) -> None:
        from greffier.wiring import assistant

        question = self.question.get().strip()
        if not question:
            return
        if self._questions_attente and self._answer_the_question(question):
            return
        if self._apprentissage_attente is not None and self._confirm_the_learning(
            question
        ):
            return
        if self._hear_an_intent(question):
            return

        engine = assistant(self.config)
        if engine is None:
            self._say("note", "Aucun rédacteur configuré : « greffier configurer ».")
            return

        in_progress = self._thread.rendered() if self._fil_reunion else ""
        if in_progress:
            material, quoi, sur = in_progress, "la transcription en direct", self._fil_reunion
        else:
            identifier = self._selection()
            if identifier is None:
                self._say("note", "Choisis une réunion dans l'onglet Réunions, "
                                   "ou démarre une réunion pour interroger le direct.")
                return
            source = self.config.paths.minutes_folder / f"{identifier}.md"
            if not source.exists():
                self._say("note", f"« {identifier} » n'a pas encore de compte rendu. "
                                   "Onglet Réunions, « Traiter ».")
                return
            material, quoi, sur = source.read_text(encoding="utf-8"), "le compte rendu", identifier

        material = self._with_the_documents(material, sur)
        self.question.delete(0, "end")
        self._say("moi", question)

        def do_it(say: Callable[[str], None]) -> Any:
            say("réflexion…")
            return engine.write_up(
                f"Question : {question}\n\n"
                f"Ce qui a été dit — {quoi} de la réunion « {sur} » :\n{material}"
            )

        self._run_job(Job(
            caption="question",
            do_it=do_it,
            done=lambda response, trouble: self._say(
                "note" if trouble else "greffier", str(trouble) if trouble else str(response)
            ),
        ))

    def spin(self) -> None:
        self.racine.after(600, self._report_missing_minutes)
        self.racine.after(900, self._remind_of_the_disclosure)
        self.racine.mainloop()

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
                for identifier in self.store.lister()[:20]
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
                + ". Onglet Réunions, « Rédiger » reprend la rédaction sans "
                "retranscrire."
            ))
            self.tabs.mark("Conversation", len(manquantes))

def open_it(config: Config) -> None:
    """The window's entry point."""
    Window(config).spin()
