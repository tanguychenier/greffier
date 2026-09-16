"""The Comptes tab: the accounts a person connects, and what she lets Claude do.

One card per service of the catalogue. The card says what the service
gives, whether it is connected, and lists the powers as boxes to tick;
a tick is a consent and is written the moment it is given. Connecting
is one of three gestures, the key pasted, the code typed on the
service's page, or nothing yet for a service that waits for an
application declared by Tansoftware. Under the cards, the journal of
what Claude did with the accounts, in plain sentences.
"""

from __future__ import annotations

import contextlib
import functools
import threading
import tkinter as tk
import webbrowser
from typing import Any

from greffier.adapters import accounts_file
from greffier.domain.accounts import Consent, Manner, Service
from greffier.domain.accounts_catalogue import CATALOGUE
from greffier.interface.appearance import Button
from greffier.interface.style import font

JOURNAL_LINES = 20


class AccountsTab:
    """Builds the tab on the window it is given, and keeps it current."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self.colours = window.colours
        self.says = window.says
        self.fields: dict[str, dict[str, tk.Entry]] = {}
        self.boxes: dict[str, dict[str, tk.BooleanVar]] = {}
        self.states: dict[str, tk.Label] = {}
        self.codes: dict[str, tk.Label] = {}
        #: Whether the sign-in by code held, per service, once it was tried
        #: here; asking the server on every paint would cost a process.
        self.signed_in: dict[str, bool] = {}
        self._build()

    def _build(self) -> None:
        window = self.window
        page = window._page("Comptes")
        header = tk.Frame(page, bg=self.colours.board)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        window._text(header, self.says("comptes.titre"), size=12, bold=True).grid(
            row=0, column=0, sticky="w")
        window._text(header, self.says("comptes.sous_titre"), size=11, pale=True,
                     wraplength=760, justify="left").grid(row=1, column=0, sticky="w")
        self.word = window._text(header, "", size=11)
        self.word.grid(row=2, column=0, sticky="w", pady=(4, 0))
        inside = window._scrolling_area(page)
        inside.columnconfigure(0, weight=1)
        rank = 0
        consents = accounts_file.read_consents()
        for service in CATALOGUE:
            rank = self._card(inside, rank, service, consents.get(service.key))
        rank = window._block(inside, rank, self.says("comptes.journal_titre"), "")
        self.journal = window._text(inside, "", size=11, wraplength=760, justify="left")
        self.journal.grid(row=rank, column=0, columnspan=2, sticky="w")
        self._say_the_journal()
        window._listen_to_the_wheel(inside)
        page.bind("<Map>", lambda _e: self._say_the_journal())

    def _card(self, inside: tk.Frame, rank: int, service: Service,
              consent: Consent | None) -> int:
        window = self.window
        c = self.colours
        rank = window._block(inside, rank, service.name, self.says(f"comptes.{service.key}_quoi"))
        state = window._text(inside, "", size=11, bold=True)
        state.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.states[service.key] = state
        rank += 1

        powers = tk.Frame(inside, bg=c.board)
        powers.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.boxes[service.key] = {}
        for power in service.powers:
            variable = tk.BooleanVar(value=bool(consent and power.key in consent.powers))
            box = tk.Checkbutton(
                powers, text=self.says(f"comptes.pouvoir_{power.key}"),
                variable=variable, bg=c.board, fg=c.ink, activebackground=c.board,
                activeforeground=c.ink, selectcolor=c.ground, font=font(12),
                highlightthickness=0, anchor="w",
                command=functools.partial(self._consent_changed, service.key),
                state="normal" if service.connectable else "disabled",
            )
            box.pack(anchor="w")
            self.boxes[service.key][power.key] = variable
        rank += 1

        if service.manner is Manner.TOKEN:
            rank = self._token_form(inside, rank, service)
        elif service.manner is Manner.DEVICE:
            rank = self._device_form(inside, rank, service)
        self._say_the_state(service)
        return rank

    def _token_form(self, inside: tk.Frame, rank: int, service: Service) -> int:
        window = self.window
        c = self.colours
        form = tk.Frame(inside, bg=c.board)
        form.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.fields[service.key] = {}
        known = accounts_file.secrets_of(service)
        for field in service.fields:
            line = tk.Frame(form, bg=c.board)
            line.pack(anchor="w", pady=(0, 4))
            window._text(line, self.says(f"comptes.champ_{field}"), size=11, pale=True,
                         width=10).pack(side="left")
            entry = window._field(line, 44)
            if field in ("jeton", "cle"):
                entry.configure(show="•")
            if known.get(field):
                entry.insert(0, known[field])
            entry.pack(side="left", ipady=4, ipadx=4)
            self.fields[service.key][field] = entry
        buttons = tk.Frame(form, bg=c.board)
        buttons.pack(anchor="w", pady=(2, 0))
        Button(buttons, self.says("comptes.connecter"),
               functools.partial(self._connect_by_token, service.key), c,
               principal=True, width=150, height=32).pack(side="left", padx=(0, 9))
        Button(buttons, self.says("comptes.deconnecter"),
               functools.partial(self._disconnect, service.key), c,
               width=150, height=32).pack(side="left", padx=(0, 9))
        if service.key_page:
            Button(buttons, self.says("comptes.obtenir_cle"),
                   functools.partial(self._open_the_key_page, service.key), c,
                   width=150, height=32).pack(side="left")
        return rank + 1

    def _device_form(self, inside: tk.Frame, rank: int, service: Service) -> int:
        window = self.window
        c = self.colours
        form = tk.Frame(inside, bg=c.board)
        form.grid(row=rank, column=0, columnspan=2, sticky="w", pady=(0, 4))
        buttons = tk.Frame(form, bg=c.board)
        buttons.pack(anchor="w")
        Button(buttons, self.says("comptes.se_connecter_code"),
               functools.partial(self._connect_by_code, service.key), c,
               principal=True, width=150, height=32).pack(side="left", padx=(0, 9))
        code = window._text(form, "", size=11, wraplength=700, justify="left")
        code.pack(anchor="w", pady=(4, 0))
        self.codes[service.key] = code
        return rank + 1

    def _say_the_state(self, service: Service) -> None:
        label = self.states[service.key]
        c = self.colours
        if not service.connectable:
            label.configure(text=self.says("comptes.attend_application"), fg=c.ink_pale)
            return
        if service.manner is Manner.TOKEN:
            connected = accounts_file.connected(service)
        else:
            connected = bool(self.signed_in.get(service.key, False))
        key = "comptes.connecte" if connected else "comptes.non_connecte"
        label.configure(text=self.says(key), fg=c.green if connected else c.ink_pale)

    def _consent_changed(self, key: str) -> None:
        powers = frozenset(p for p, var in self.boxes[key].items() if var.get())
        with contextlib.suppress(OSError):
            accounts_file.write_consent(Consent(key, powers))
        self.word.configure(text=self.says("comptes.applique_prochaine_reponse"))

    def _connect_by_token(self, key: str) -> None:
        service = next(s for s in CATALOGUE if s.key == key)
        values = {field: entry.get().strip() for field, entry in self.fields[key].items()}
        if any(not values[field] for field in service.fields):
            self.word.configure(text=self.says("comptes.champ_manquant"))
            return
        with contextlib.suppress(OSError):
            accounts_file.store_secrets(service, values)
        self._say_the_state(service)
        self.word.configure(text=self.says("comptes.connexion_reussie", service=service.name))

    def _disconnect(self, key: str) -> None:
        service = next(s for s in CATALOGUE if s.key == key)
        with contextlib.suppress(OSError):
            accounts_file.forget_secrets(service)
            accounts_file.write_consent(Consent(key, frozenset()))
        for entry in self.fields.get(key, {}).values():
            entry.delete(0, "end")
        for variable in self.boxes[key].values():
            variable.set(False)
        self._say_the_state(service)
        self.word.configure(text=self.says("comptes.deconnecte", service=service.name))

    def _open_the_key_page(self, key: str) -> None:
        service = next(s for s in CATALOGUE if s.key == key)
        values = {field: entry.get().strip() for field, entry in self.fields[key].items()}
        try:
            page = service.key_page.format(**values)
        except (KeyError, IndexError):
            page = service.key_page
        if "{" in page or not page.startswith("http"):
            self.word.configure(text=self.says("comptes.adresse_d_abord"))
            return
        webbrowser.open(page)

    def _connect_by_code(self, key: str) -> None:
        """Signs in through the service's own page, the code shown here meanwhile."""
        service = next(s for s in CATALOGUE if s.key == key)
        root = self.window.root
        code_label = self.codes[key]
        code_label.configure(text=self.says("comptes.connexion_en_cours"))

        def show(url: str, code: str) -> None:
            def paint() -> None:
                code_label.configure(text=self.says("comptes.code_a_saisir", url=url, code=code))
                with contextlib.suppress(tk.TclError):
                    root.clipboard_clear()
                    root.clipboard_append(code)
                webbrowser.open(url)

            root.after(0, paint)

        def sign_in() -> None:
            done = accounts_file.sign_in(service, show)

            def finish() -> None:
                self.signed_in[key] = done
                self._say_the_state(service)
                code_label.configure(text=self.says(
                    "comptes.connexion_reussie" if done else "comptes.connexion_ratee",
                    service=service.name))

            root.after(0, finish)

        threading.Thread(target=sign_in, daemon=True).start()

    def _say_the_journal(self) -> None:
        deeds = accounts_file.deeds(self.window.config.paths.data, last=JOURNAL_LINES)
        if not deeds:
            self.journal.configure(text=self.says("comptes.journal_vide"))
            return
        name = self.window.config.assistant.name
        lines = []
        for deed in reversed(deeds):
            service = next((s.name for s in CATALOGUE if s.key == deed.service), deed.service)
            what = self.says(f"comptes.fait_{deed.power}", service=service)
            lines.append(f"{deed.at[11:16]}  {name} {what}")
        self.journal.configure(text="\n".join(lines))
