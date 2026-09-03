"""La fenêtre de Greffier : une application qu'on lance, pas une icône.

Il y avait trois demi-interfaces : une icône de barre de menus en Swift sur
macOS, une icône de zone de notification ailleurs, et des questions posées dans
un terminal que personne ne voit quand le traitement tourne détaché. Trois
comportements à maintenir, aucun complet.

Une fenêtre les remplace. Tkinter parce qu'il est dans la bibliothèque standard :
rien à installer, comme l'installeur du projet qui ne dépend que d'elle. Son
apparence ne vient pas de ses widgets, qui datent, mais de formes dessinées —
voir `apparence`.

Deux principes de mise en page, tirés de défauts constatés :

- **tout est en grille avec des poids explicites.** Un `pack` en `expand` suivi
  d'un bouton pousse ce bouton hors de la fenêtre dès qu'on la redimensionne ;
  c'est arrivé au bouton « Demander ».
- **les commandes disponibles suivent l'état.** Un bouton unique qui change de
  texte n'apprend pas ce qu'on peut faire. À l'arrêt on démarre ; en cours on
  suspend ou on termine ; en pause on reprend ou on termine.

Ce module n'implémente aucune règle. Il lit l'état, affiche, et appelle. Tout ce
qui décide vit dans le domaine et l'application, et se teste sans écran.
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

from greffier.adaptateurs.niveaux_direct import Releve, relever
from greffier.application.suivre import (
    GENRE_CORRECTION,
    GENRE_ETAT,
    GENRE_REUNION,
    demander,
    fichiers,
    lire_depuis,
    rejouer,
)
from greffier.config import Config
from greffier.domaine.canaux import QuiParle
from greffier.domaine.direct import Fil, TourDirect
from greffier.domaine.modeles import Phase
from greffier.emplacements import situer_tcl
from greffier.interface.apparence import Bouton, Defileur, Liste, Onglets, Vumetre
from greffier.interface.lisible import etat_du_direct, horloge, sujet_lisible
from greffier.interface.style import palette, police

#: Cadence de rafraîchissement. Quatre fois par seconde suffit à suivre la
#: parole, et laisse la machine tranquille pendant une heure de réunion.
PERIODE_MS = 250

#: Les micros sont relus moins souvent que l'état : la lecture du matériel coûte
#: 60 ms, ce qui est négligeable une fois par seconde et inutile quatre fois.
PERIODE_MICROS_MS = 1000

#: Cadence de la respiration du point rouge. Assez fin pour un fondu lisse,
#: assez large pour ne rien coûter sur une heure de réunion.
PULSATION_MS = 50

#: Durée d'un cycle de respiration, en secondes.
PULSATION_S = 1.6


def _degrade(depuis: str, vers: str, part: float) -> str:
    """Une couleur entre deux autres, en hexadécimal — le fondu du point rouge."""
    a = tuple(int(depuis[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(vers[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * part):02x}" for x, y in zip(a, b, strict=True))


def _police_titre(taille: int) -> tuple[str, int, str]:
    """Une empreinte plus éditoriale pour le nom de la réunion.

    Le seul texte de la fenêtre qui n'a pas besoin de ressembler à un bouton.
    Georgia est du système sur macOS et Windows ; DejaVu Serif ailleurs, comme
    le repli de `police`.
    """
    famille = {"Darwin": "Georgia", "Windows": "Georgia"}.get(platform.system(), "DejaVu Serif")
    return (famille, taille, "bold")

#: Largeur réservée aux libellés des vumètres. Fixée plutôt que laissée à la
#: grille, qui rejetait les barres à l'autre bout de la carte.
_LIBELLE = 84

#: Colonnes dont le contenu est un nombre, donc aligné à droite.
_NOMBRES = frozenset({"voix", "mots", "duree", "part"})

_LIBELLES_VOIX = {
    QuiParle.PERSONNE: "",
    QuiParle.TOI: "tu parles",
    QuiParle.LES_AUTRES: "les autres parlent",
    QuiParle.LES_DEUX: "vous parlez en même temps",
}


@dataclass
class Travail:
    """Une tâche longue, portée par un fil, qui rend compte à la fenêtre."""

    intitule: str
    faire: Callable[[Callable[[str], None]], Any]
    #: Appelé sur le fil de l'interface, avec le résultat ou l'exception.
    fini: Callable[[Any, Exception | None], None] = lambda _resultat, _souci: None
    messages: queue.Queue[str] = field(default_factory=queue.Queue)


class Fenetre:
    """Assemble l'interface et la tient à jour."""

    def __init__(self, config: Config) -> None:
        from greffier.composition import depot, enregistrement

        self.config = config
        self.machine = enregistrement(config)
        self.depot = depot(config)
        self.couleurs = palette(config.apparence.theme)
        self.travaux: list[Travail] = []
        self._phase_peinte: Phase | None = None
        self._micros_connus: tuple[tuple[str, str], ...] = ()
        # Le fil de la réunion en cours, reconstruit depuis le journal que le
        # processus d'écoute publie. La fenêtre y applique les corrections tout
        # de suite, sans attendre la tranche suivante.
        self._fil = Fil()
        self._fil_reunion = ""
        self._fil_position = 0
        self._fil_annonce = ""
        self._menu: tk.Menu | None = None

        situer_tcl()
        self.racine = tk.Tk()
        self.racine.title("Greffier")
        # Sans cela, macOS affiche « python3 » dans la barre de menus et le Dock.
        with contextlib.suppress(tk.TclError):
            self.racine.tk.call("tk", "appname", "Greffier")
        self.racine.minsize(880, 660)
        # Fermer la fenêtre doit être un acte volontaire : Tk quitte le
        # processus dès que sa fenêtre disparaît, et la capture — portée par ce
        # processus — meurt avec, net, sans recoller les morceaux ni prévenir.
        # Constaté en réunion réelle : fenêtre disparue, enregistrement coupé.
        self.racine.protocol("WM_DELETE_WINDOW", self._fermer)
        # Sans elle, la fenêtre se redimensionne à chaque changement d'onglet :
        # `pack` calcule la taille du parent d'après celle du seul enfant
        # affiché, et les onglets n'ont pas tous le même contenu. Une géométrie
        # posée une fois pour toutes fixe la taille, laissée au choix de
        # l'utilisateur ensuite.
        self.racine.geometry("880x660")
        self.racine.configure(bg=self.couleurs.fond)
        self._styler_listes()
        self._construire()
        self._rafraichir()
        self._suivre_les_micros()

    # ------------------------------------------------------------- apparence

    def _styler_listes(self) -> None:
        """Les listes restent des widgets Tk : au moins qu'elles suivent la palette."""
        c = self.couleurs
        style = ttk.Style()
        with contextlib.suppress(tk.TclError):
            style.theme_use("clam")
        # `borderwidth=0` ne suffit pas : sous « clam », le cadre de la liste est
        # peint par l'élément `Treeview.field`, qui tire ses trois couleurs de la
        # configuration et non du relief. Sans les poser, la liste garde un
        # liseré vert-de-gris à angles droits — la « pièce étrangère » déjà
        # retirée aux listes déroulantes.
        style.configure(
            "Greffier.Treeview",
            background=c.carte, fieldbackground=c.carte, foreground=c.encre,
            borderwidth=0, relief="flat", rowheight=29, font=police(12),
            bordercolor=c.carte, lightcolor=c.carte, darkcolor=c.carte,
        )
        style.configure(
            "Greffier.Treeview.Heading",
            background=c.carte, foreground=c.encre_pale, borderwidth=0,
            relief="flat", font=police(11, gras=True), padding=(6, 8),
        )
        style.map("Greffier.Treeview",
                  background=[("selected", c.survol)], foreground=[("selected", c.encre)])
        style.map("Greffier.Treeview.Heading", background=[("active", c.carte)])
        # La liste déroulante de Tk arrive avec le bouton fléché carré et gris
        # du thème « clam » : à côté des boutons dessinés, elle jure. On lui
        # donne le fond des champs, une flèche à l'encre pâle, et un liseré
        # plutôt qu'un relief.
        style.configure("Greffier.TCombobox", arrowsize=12, padding=6,
                        borderwidth=1, relief="flat", arrowcolor=c.encre_pale,
                        bordercolor=c.filet, lightcolor=c.fond, darkcolor=c.fond,
                        insertcolor=c.encre)
        style.map(
            "Greffier.TCombobox",
            fieldbackground=[("readonly", c.fond)],
            foreground=[("readonly", c.encre), ("disabled", c.calme)],
            selectbackground=[("readonly", c.fond)],
            selectforeground=[("readonly", c.encre)],
            background=[("readonly", c.fond), ("active", c.survol)],
            arrowcolor=[("active", c.encre), ("disabled", c.calme)],
            bordercolor=[("focus", c.encre_pale), ("hover", c.encre_pale)],
        )
        # Le menu qui se déploie est une liste Tk classique, hors du thème ttk :
        # elle ne s'atteint que par la base de données d'options.
        for option, valeur in (
            ("*TCombobox*Listbox.background", c.carte),
            ("*TCombobox*Listbox.foreground", c.encre),
            ("*TCombobox*Listbox.selectBackground", c.survol),
            ("*TCombobox*Listbox.selectForeground", c.encre),
            ("*TCombobox*Listbox.borderWidth", "0"),
            ("*TCombobox*Listbox.highlightThickness", "0"),
            ("*TCombobox*Listbox.font", "TkDefaultFont"),
        ):
            with contextlib.suppress(tk.TclError):
                self.racine.option_add(option, valeur)

    def _texte(self, parent: tk.Misc, contenu: str, taille: int = 13,
               gras: bool = False, pale: bool = False, **options: Any) -> tk.Label:
        return tk.Label(
            parent, text=contenu, bg=parent.cget("bg"), anchor="w",
            fg=self.couleurs.encre_pale if pale else self.couleurs.encre,
            font=police(taille, gras), **options,
        )

    def _champ(self, parent: tk.Misc, largeur: int | None = None) -> tk.Entry:
        c = self.couleurs
        options: dict[str, Any] = {} if largeur is None else {"width": largeur}
        return tk.Entry(
            parent, relief="flat", bg=c.fond, fg=c.encre, font=police(12),
            insertbackground=c.encre, highlightthickness=1,
            highlightbackground=c.filet, highlightcolor=c.accent, **options,
        )

    def _carte(self, parent: tk.Misc, sticky: str = "nsew") -> tk.Frame:
        """Une carte avec un soupçon d'ombre portée.

        Deux cadres dans la même cellule de grille plutôt qu'un `Canvas` : Tk
        empile ce qui partage une cellule dans l'ordre de création, donc le
        second (la carte) recouvre le premier (l'ombre), décalé de quelques
        pixels en bas à droite — sans rien changer à la façon dont la taille
        remonte des enfants, contrairement à un `place()` qui l'aurait cassée.
        """
        c = self.couleurs
        ombre = tk.Frame(parent, bg=c.filet)
        ombre.grid(row=0, column=0, sticky=sticky, padx=(3, 0), pady=(3, 0))
        carte = tk.Frame(parent, bg=c.carte, highlightbackground=c.filet,
                         highlightthickness=1)
        carte.grid(row=0, column=0, sticky=sticky, padx=(0, 3), pady=(0, 3))
        return carte

    # ------------------------------------------------------------ assemblage

    def _construire(self) -> None:
        c = self.couleurs
        self.racine.columnconfigure(0, weight=1)
        self.racine.rowconfigure(0, weight=1)
        corps = tk.Frame(self.racine, bg=c.fond)
        corps.grid(row=0, column=0, sticky="nsew", padx=24, pady=22)
        corps.columnconfigure(0, weight=1)
        corps.rowconfigure(1, weight=1)

        self._construire_etat(corps)
        self.onglets = Onglets(corps, c)
        self.onglets.grid(row=1, column=0, sticky="nsew", pady=(22, 0))
        self._onglet_reunions()
        self._onglet_direct()
        self._onglet_voix()
        self._onglet_conversation()
        self._onglet_reglages()
        self.etat_bas = self._texte(corps, "", taille=11, pale=True)
        self.etat_bas.grid(row=2, column=0, sticky="ew", pady=(14, 0))

    def _construire_etat(self, parent: tk.Frame) -> None:
        c = self.couleurs
        carte = self._carte(parent, sticky="ew")
        carte.columnconfigure(0, weight=1)
        dedans = tk.Frame(carte, bg=c.carte)
        dedans.grid(row=0, column=0, sticky="ew", padx=24, pady=22)
        dedans.columnconfigure(0, weight=1)

        ligne = tk.Frame(dedans, bg=c.carte)
        ligne.grid(row=0, column=0, sticky="ew")
        ligne.columnconfigure(1, weight=1)
        self.pastille = tk.Canvas(ligne, width=12, height=12, highlightthickness=0,
                                  bg=c.carte)
        self.pastille.grid(row=0, column=0, sticky="w", pady=(8, 0))
        self._point = self.pastille.create_oval(1, 1, 11, 11, fill=c.calme, outline="")
        self.titre = self._texte(ligne, "Prêt", taille=21, gras=True)
        self.titre.configure(font=_police_titre(21))
        self.titre.grid(row=0, column=1, sticky="w", padx=(11, 0))
        self.chrono = self._texte(ligne, "", taille=27)
        self.chrono.grid(row=0, column=2, sticky="e")

        self.detail = self._texte(dedans, "Aucun enregistrement en cours.",
                                  taille=12, pale=True)
        self.detail.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        mesures = tk.Frame(dedans, bg=c.carte)
        mesures.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        mesures.columnconfigure(1, weight=1)
        self.vu_toi = self._ligne_vumetre(mesures, "Toi", 0)
        self.vu_autres = self._ligne_vumetre(mesures, "Les autres", 1)
        self.qui = self._texte(mesures, "", taille=11, gras=True)
        self.qui.configure(fg=c.vert)
        self.qui.grid(row=2, column=1, sticky="w", pady=(7, 0))

        self.commandes = tk.Frame(dedans, bg=c.carte)
        self.commandes.grid(row=3, column=0, sticky="ew", pady=(20, 0))
        self._construire_commandes()
        self._respirer()

    def _ligne_vumetre(self, parent: tk.Frame, intitule: str, rang: int) -> Vumetre:
        self._texte(parent, intitule, taille=11, pale=True).grid(
            row=rang, column=0, sticky="w", pady=3
        )
        parent.columnconfigure(0, minsize=_LIBELLE)
        barre = Vumetre(parent, self.couleurs, largeur=340)
        barre.grid(row=rang, column=1, sticky="w", pady=3)
        return barre

    def _construire_commandes(self) -> None:
        """Les trois jeux de commandes, construits une fois, montrés tour à tour.

        Ils étaient détruits et reconstruits à chaque changement d'état, et cela
        faisait tomber le processus : Tk envoie encore ses événements de survol
        au bouton qu'on vient de cliquer, et le trouvait détruit. Le rapport de
        plantage nomme « Tk_MacOSXGetTkWindow », sur le fil principal.

        Montrer et cacher n'a pas ce défaut, et le clic reste toujours servi par
        un widget vivant.
        """
        c = self.couleurs
        self.jeux: dict[Phase, tk.Frame] = {}

        repos = tk.Frame(self.commandes, bg=c.carte)
        Bouton(repos, "Démarrer la réunion", self._demarrer, c,
               principal=True, largeur=192, hauteur=38).pack(side="left")
        # Aucun sujet à saisir : c'est le compte rendu qui le donnera, déduit de
        # ce qui a été dit. Demander à l'avance obligerait à savoir de quoi une
        # réunion va parler, et Greffier est là pour l'écouter.
        self._texte(repos, "Micro", taille=11, pale=True).pack(side="left", padx=(20, 8))
        self.micro = Liste(repos, c, largeur=286, hauteur=36)
        self.micro.pack(side="left")
        self._charger_micros()
        self.jeux[Phase.REPOS] = repos

        en_cours = tk.Frame(self.commandes, bg=c.carte)
        Bouton(en_cours, "Mettre en pause", self._suspendre, c,
               largeur=156, hauteur=38).pack(side="left", padx=(0, 10))
        Bouton(en_cours, "Terminer la réunion", self._terminer, c,
               principal=True, largeur=192, hauteur=38).pack(side="left")
        self.jeux[Phase.ENREGISTREMENT] = en_cours

        pause = tk.Frame(self.commandes, bg=c.carte)
        Bouton(pause, "Reprendre", self._relancer, c, principal=True,
               largeur=136, hauteur=38).pack(side="left", padx=(0, 10))
        Bouton(pause, "Terminer la réunion", self._terminer, c,
               largeur=192, hauteur=38).pack(side="left")
        self.jeux[Phase.PAUSE] = pause

        self._montrer_commandes(Phase.REPOS)

    def _montrer_commandes(self, phase: Phase) -> None:
        """N'affiche que les commandes possibles dans cet état."""
        voulu = self.jeux.get(phase, self.jeux[Phase.REPOS])
        for jeu in self.jeux.values():
            if jeu is voulu:
                jeu.pack(fill="x", anchor="w")
            else:
                jeu.pack_forget()

    def _page(self, intitule: str) -> tk.Frame:
        page = self.onglets.ajouter(intitule)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        carte = self._carte(page)
        carte.columnconfigure(0, weight=1)
        carte.rowconfigure(0, weight=1)
        dedans = tk.Frame(carte, bg=self.couleurs.carte)
        dedans.grid(row=0, column=0, sticky="nsew", padx=20, pady=18)
        dedans.columnconfigure(0, weight=1)
        return dedans

    def _liste(self, parent: tk.Frame, colonnes: tuple[tuple[str, str, int], ...],
               rang: int = 0) -> ttk.Treeview:
        arbre = ttk.Treeview(
            parent, columns=[x[0] for x in colonnes], show="headings",
            style="Greffier.Treeview", selectmode="browse", takefocus=False,
        )
        for indice, (cle, intitule, largeur) in enumerate(colonnes):
            # Un nombre se lit aligné à droite, un intitulé à gauche, et
            # l'en-tête suit son contenu plutôt que de rester centré.
            if cle in _NOMBRES:
                arbre.heading(cle, text=intitule, anchor="e")
                arbre.column(cle, width=largeur, anchor="e", stretch=False)
            else:
                arbre.heading(cle, text=intitule, anchor="w")
                arbre.column(cle, width=largeur, anchor="w", stretch=indice == 0)
        arbre.grid(row=rang, column=0, sticky="nsew")
        # Sans lui, une liste plus longue que la fenêtre n'a aucun moyen visible
        # de se dérouler : ni ascenseur, ni indice qu'il en manque un.
        ascenseur = Defileur(parent, self.couleurs, arbre.yview)
        ascenseur.grid(row=rang, column=1, sticky="ns", padx=(4, 0))
        arbre.configure(yscrollcommand=ascenseur.set)
        parent.columnconfigure(1, minsize=12)
        parent.rowconfigure(rang, weight=1)
        return arbre

    # ---------------------------------------------------------------- onglets

    def _onglet_reunions(self) -> None:
        dedans = self._page("Réunions")
        self.liste = self._liste(dedans, (
            ("date", "Réunion", 320), ("voix", "Personnes", 90),
            ("mots", "Mots", 80), ("compte_rendu", "Compte rendu", 120),
        ))
        actions = tk.Frame(dedans, bg=self.couleurs.carte)
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        for intitule, action, largeur in (
            ("Traiter", self._traiter_selection, 100),
            ("Ouvrir", self._ouvrir_compte_rendu, 96),
            ("Envoyer par courriel", self._envoyer_selection, 180),
            ("Rafraîchir", self._charger_reunions, 116),
        ):
            Bouton(actions, intitule, action, self.couleurs,
                   largeur=largeur, hauteur=34).pack(side="left", padx=(0, 9))
        self.liste.bind("<<TreeviewSelect>>", lambda _e: self._charger_voix())
        self._charger_reunions()

    def _onglet_direct(self) -> None:
        """Ce qui se dit, pendant que ça se dit — et corrigeable d'un clic.

        Un `Text` et non une liste : on lit une conversation, pas un tableau, et
        une phrase de trente mots doit revenir à la ligne. Chaque nom de
        locuteur porte son propre repère cliquable, ce qui permet de corriger
        l'attribution sans quitter la réunion des yeux.
        """
        c = self.couleurs
        dedans = self._page("En direct")
        self.direct_etat = self._texte(
            dedans,
            "Le fil s'affiche ici pendant la réunion. Clique sur un nom pour "
            "corriger qui parle — un « ? » signale un nom deviné par la voix, "
            "pas encore confirmé.",
            taille=11, pale=True, wraplength=740, justify="left",
        )
        self.direct_etat.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        cadre = tk.Frame(dedans, bg=c.carte)
        cadre.grid(row=1, column=0, sticky="nsew")
        cadre.columnconfigure(0, weight=1)
        cadre.rowconfigure(0, weight=1)
        dedans.rowconfigure(1, weight=1)

        self.fil_texte = tk.Text(
            cadre, wrap="word", relief="flat", bg=c.carte, fg=c.encre,
            padx=0, pady=0, font=police(12), state="disabled",
            highlightthickness=0, cursor="arrow", spacing3=6,
        )
        self.fil_texte.grid(row=0, column=0, sticky="nsew")
        ascenseur = Defileur(cadre, c, self.fil_texte.yview)
        ascenseur.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.fil_texte.configure(yscrollcommand=ascenseur.set)
        self.fil_texte.tag_configure("heure", foreground=c.calme, font=police(10))
        # Un nom sûr en encre, un nom deviné en ambre : la couleur dit où
        # regarder, ce qu'une liste uniforme ne fait pas.
        self.fil_texte.tag_configure("sur", foreground=c.encre, font=police(11, gras=True))
        self.fil_texte.tag_configure("doute", foreground=c.ambre, font=police(11, gras=True))
        # `lmargin2` porte les lignes de continuation : sans lui, une réplique
        # qui dépasse la largeur repart contre la marge, sous l'heure et le nom,
        # et l'œil ne retrouve plus la colonne du texte. Mesuré à la capture :
        # l'heure et le nom tiennent 90 px aux tailles de police d'ici.
        self.fil_texte.tag_configure("dit", foreground=c.encre, lmargin2=90)

    # -------------------------------------------------------------- le direct

    def _suivre_le_direct(self, etat: Any) -> None:
        """Lit ce que le processus d'écoute a publié depuis la dernière fois.

        Quatre fois par seconde, mais en ne lisant que les octets ajoutés : une
        heure de réunion relue à chaque tour coûterait pour rien.
        """
        if etat.identifiant != self._fil_reunion:
            self._oublier_le_direct(etat.identifiant)
        if not self._fil_reunion:
            return
        journal, _ = fichiers(self.config.chemins.direct, self._fil_reunion)
        lignes, self._fil_position = lire_depuis(journal, self._fil_position)
        if not lignes:
            return
        for ligne in lignes:
            if ligne.get("genre") == GENRE_ETAT:
                self._fil_annonce = str(ligne.get("message", ""))
        deja = len(self._fil.tours)
        # Une réunion de voix change l'attribution de tours déjà affichés : le
        # fil se repeint en entier, comme pour une correction.
        remaniement = {GENRE_CORRECTION, GENRE_REUNION}
        corrige = any(ligne.get("genre") in remaniement for ligne in lignes)
        rejouer(lignes, self._fil)
        if corrige:
            # Une correction touche des phrases déjà affichées : il faut reprendre
            # le fil entier, l'ajout seul ne les corrigerait pas.
            self._repeindre_le_direct()
        else:
            self._ajouter_au_direct(self._fil.tours[deja:])
        self._dire_l_etat_du_direct()

    def _oublier_le_direct(self, identifiant: str) -> None:
        """Repart de zéro : une autre réunion, un autre fil."""
        self._fil = Fil()
        self._fil_reunion = identifiant
        self._fil_position = 0
        self._fil_annonce = ""
        self._vider(self.fil_texte)
        self._dire_l_etat_du_direct()

    def _dire_l_etat_du_direct(self) -> None:
        self.direct_etat.configure(
            text=etat_du_direct(
                en_reunion=bool(self._fil_reunion),
                annonce=self._fil_annonce,
                phrases=len(self._fil.tours),
            )
        )

    def _vider(self, zone: tk.Text) -> None:
        zone.configure(state="normal")
        zone.delete("1.0", "end")
        zone.configure(state="disabled")

    def _repeindre_le_direct(self) -> None:
        self._vider(self.fil_texte)
        self._ajouter_au_direct(self._fil.tours)

    def _ajouter_au_direct(self, tours: list[TourDirect]) -> None:
        if not tours:
            return
        # Le défilement ne suit que si l'on était déjà en bas : sinon on
        # arracherait de l'écran le passage que quelqu'un est en train de relire.
        suivait = self.fil_texte.yview()[1] > 0.999
        self.fil_texte.configure(state="normal")
        for tour in tours:
            self._ecrire_un_tour(tour)
        self.fil_texte.configure(state="disabled")
        if suivait:
            self.fil_texte.see("end")

    def _ecrire_un_tour(self, tour: TourDirect) -> None:
        voix = self._fil.voix.get(tour.voix)
        ferme = voix is not None and voix.certitude.ferme
        repere = f"tour{tour.numero}"
        self.fil_texte.insert("end", f"{horloge(tour.intervalle.debut)}  ", "heure")
        self.fil_texte.insert(
            "end", self._fil.etiquette(tour.voix), ("sur" if ferme else "doute", repere)
        )
        self.fil_texte.insert("end", f"   {tour.texte}\n", "dit")
        self.fil_texte.tag_bind(
            repere, "<Button-1>",
            functools.partial(self._menu_locuteur, numero=tour.numero),
        )
        self.fil_texte.tag_bind(
            repere, "<Enter>", lambda _e: self.fil_texte.configure(cursor="pointinghand")
        )
        self.fil_texte.tag_bind(
            repere, "<Leave>", lambda _e: self.fil_texte.configure(cursor="arrow")
        )

    def _menu_locuteur(self, evenement: Any, numero: int) -> None:
        """Le menu de correction : qui parle vraiment.

        Deux portées, et la première est le cas courant : quand l'outil se
        trompe de personne, il se trompe pour tous les passages de cette voix.
        « Seulement cette phrase » sert aux chevauchements, où le groupe est bon
        mais un passage y est tombé par erreur.
        """
        tour = next((t for t in self._fil.tours if t.numero == numero), None)
        if tour is None:
            return
        voix = self._fil.voix.get(tour.voix)
        noms = self._fil.noms_proposables()
        menu = tk.Menu(self.racine, tearoff=0, font=police(12))
        if voix is not None and voix.nommable:
            menu.add_command(
                label=f"Toute la voix « {self._fil.etiquette(tour.voix)} » est :",
                state="disabled",
            )
            self._garnir(menu, noms, numero, toute_la_voix=True)
            menu.add_separator()
            phrase = tk.Menu(menu, tearoff=0, font=police(12))
            self._garnir(phrase, noms, numero, toute_la_voix=False)
            menu.add_cascade(label="Seulement cette phrase…", menu=phrase)
        else:
            # Le fourre-tout des bribes mélange les personnes : le nommer en
            # entier attribuerait à quelqu'un les « oui » de tout le monde.
            menu.add_command(label="Cette phrase est de :", state="disabled")
            self._garnir(menu, noms, numero, toute_la_voix=False)
        # Gardée en attribut : un menu que Python ramasse pendant son affichage
        # laisse une fenêtre fantôme, et le clic ne sert plus personne.
        self._menu = menu
        try:
            menu.tk_popup(evenement.x_root, evenement.y_root)
        finally:
            menu.grab_release()

    def _garnir(
        self, menu: tk.Menu, noms: list[str], numero: int, toute_la_voix: bool
    ) -> None:
        # Un nom déjà porté par une autre voix de cette réunion **réunit** les
        # deux : c'est exactement ce qu'il faut quand l'outil a découpé une
        # personne en plusieurs voix, et ça marche pour autant de voix qu'il en
        # a créées. Rien ne le disait, donc personne ne pouvait le deviner.
        ailleurs = self._noms_portes_ailleurs(numero)
        for nom in noms:
            suffixe = "   ⟵ réunir les deux voix" if nom in ailleurs else ""
            menu.add_command(
                label=f"{nom}{suffixe}",
                command=functools.partial(
                    self._corriger_le_direct, numero, nom, toute_la_voix
                ),
            )
        menu.add_command(
            label="Autre nom…",
            command=functools.partial(self._demander_un_nom, numero, toute_la_voix),
        )

    def _noms_portes_ailleurs(self, numero: int) -> set[str]:
        """Les noms que porte déjà une **autre** voix que celle-ci."""
        tour = next((t for t in self._fil.tours if t.numero == numero), None)
        return {
            voix.nom for identifiant, voix in self._fil.voix.items()
            if voix.nom and (tour is None or identifiant != tour.voix)
        }

    def _demander_un_nom(self, numero: int, toute_la_voix: bool) -> None:
        from tkinter import simpledialog

        nom = simpledialog.askstring(
            "Greffier", "Qui parle ?", parent=self.racine
        )
        if nom and nom.strip():
            self._corriger_le_direct(numero, nom.strip(), toute_la_voix)

    def _corriger_le_direct(self, numero: int, nom: str, toute_la_voix: bool) -> None:
        """Applique la correction ici, et la transmet à qui écoute.

        Ici d'abord : un clic doit se voir tout de suite, pas dans dix secondes.
        Le processus d'écoute la reprendra à sa prochaine tranche, la publiera
        en confirmation, et versera l'empreinte à la banque de voix — c'est ce
        qui fait que le compte rendu final retrouvera la personne tout seul.
        """
        try:
            self._fil.corriger(numero, nom, toute_la_voix)
        except (KeyError, ValueError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        _, demandes = fichiers(self.config.chemins.direct, self._fil_reunion)
        try:
            demander(demandes, numero, nom, toute_la_voix)
        except OSError as souci:
            messagebox.showerror(
                "Greffier",
                f"La correction est affichée mais n'a pas pu être transmise : {souci}",
            )
        self._repeindre_le_direct()

    def _onglet_voix(self) -> None:
        dedans = self._page("Voix")
        self._texte(
            dedans,
            "Nommer une voix la met en banque : elle sera reconnue seule aux réunions "
            "suivantes, sans qu'aucun prénom soit prononcé.",
            taille=11, pale=True, wraplength=740, justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.voix = self._liste(dedans, (
            ("voix", "Voix", 100), ("duree", "Durée", 90),
            ("part", "Part", 80), ("nom", "Nom", 260),
        ), rang=1)

        saisie = tk.Frame(dedans, bg=self.couleurs.carte)
        saisie.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        # Le champ était un rectangle gris sans intitulé : rien ne disait ce
        # qu'on y tape, et « Nommer » à côté ne suffit pas — on peut aussi
        # croire qu'il faut y écrire le numéro de la voix.
        self._texte(saisie, "Prénom", taille=11, pale=True).pack(
            side="left", padx=(0, 9)
        )
        self.champ_nom = self._champ(saisie, largeur=20)
        self.champ_nom.pack(side="left", ipady=7, ipadx=5)
        self.champ_nom.bind("<Return>", lambda _e: self._nommer())
        Bouton(saisie, "Nommer", self._nommer, self.couleurs, principal=True,
               largeur=110, hauteur=34).pack(side="left", padx=(11, 9))
        Bouton(saisie, "Écouter 10 s", self._ecouter, self.couleurs,
               largeur=140, hauteur=34).pack(side="left")

    def _onglet_conversation(self) -> None:
        c = self.couleurs
        dedans = self._page("Conversation")
        cadre = tk.Frame(dedans, bg=c.carte)
        cadre.grid(row=0, column=0, sticky="nsew")
        cadre.columnconfigure(0, weight=1)
        cadre.rowconfigure(0, weight=1)
        dedans.rowconfigure(0, weight=1)

        self.fil = tk.Text(cadre, wrap="word", relief="flat", bg=c.carte, fg=c.encre,
                           padx=0, pady=0, font=police(12), state="disabled",
                           highlightthickness=0, cursor="arrow")
        self.fil.grid(row=0, column=0, sticky="nsew")
        ascenseur = Defileur(cadre, c, self.fil.yview)
        ascenseur.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.fil.configure(yscrollcommand=ascenseur.set)
        self.fil.tag_configure("qui", foreground=c.encre_pale, spacing1=12, spacing3=3,
                               font=police(10, gras=True))
        self.fil.tag_configure("dit", foreground=c.encre, spacing3=8)
        self.fil.tag_configure("note", foreground=c.encre_pale, spacing1=5, spacing3=10,
                               font=police(11))

        saisie = tk.Frame(dedans, bg=c.carte)
        # Grille et non pack : un champ en « expand » suivi d'un bouton pousse
        # ce bouton hors de la fenêtre dès qu'on la redimensionne.
        saisie.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        saisie.columnconfigure(0, weight=1)
        self.question = self._champ(saisie)
        self.question.grid(row=0, column=0, sticky="ew", ipady=8, ipadx=5)
        self.question.bind("<Return>", lambda _e: self._demander())
        Bouton(saisie, "Demander", self._demander, self.couleurs, principal=True,
               largeur=124, hauteur=36).grid(row=0, column=1, padx=(11, 0))
        self._dire("note", "Pose une question sur la réunion choisie dans l'onglet "
                           "Réunions : ce qui a été décidé, ce qui reste ouvert, à qui "
                           "envoyer le compte rendu.")

    # ---------------------------------------------------------------- réglages

    #: Les modèles de transcription connus, du plus juste au plus rapide. Seuls
    #: ceux réellement présents sur le disque sont proposés : offrir un modèle
    #: absent promettrait un téléchargement d'un gigaoctet au premier clic sur
    #: « Démarrer », c'est-à-dire au pire moment.
    MODELES_TRANSCRIPTION = (
        ("large-v3-turbo", "large-v3-turbo — le plus juste, conseillé"),
        ("large-v3", "large-v3 — plus lent, sans gain mesuré ici"),
        ("small", "small — rapide, pour les postes modestes"),
    )
    THEMES = (("systeme", "Selon le système"), ("clair", "Clair"), ("sombre", "Sombre"))
    #: Les langues proposées. Une liste et non un champ libre : « fr » ne se
    #: devine pas, et une faute de code faisait transcrire en silence dans la
    #: mauvaise langue. Whisper en connaît une centaine ; celles-ci couvrent ce
    #: qu'une réunion de travail rencontre, et la détection automatique répond
    #: pour le reste.
    LANGUES = (
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
    #: Combien de personnes participent. « Déduit » laisse le regroupement
    #: trouver le nombre — ce qu'il fait mal en présentiel, où toutes les voix
    #: passent par le même micro : mesuré, quatre voix pour deux personnes.
    #: Annoncer le nombre force exactement autant de groupes, et c'est la seule
    #: chose que la machine ne peut pas savoir.
    PARTICIPANTS = (("", "Déduit de l'enregistrement"),
                    *((str(n), f"{n} personnes") for n in range(2, 13)))
    PERIODES_DIRECT = (("5.0", "5 s — très réactif, plus de calcul"),
                       ("10.0", "10 s — conseillé"),
                       ("20.0", "20 s — économe, l'affichage suit de loin"))

    def _onglet_reglages(self) -> None:
        """Les réglages qu'on change vraiment, sans ouvrir un fichier.

        Ceux qui sont des listes — vocabulaire, mots qui ne sont jamais des
        prénoms — restent au fichier : un formulaire les tronquerait, et un
        éditeur les tient mieux. Ce qui est réglé ici est écrit dans
        `config.toml`, la source d'où le reste de la chaîne lit déjà.
        """
        page = self._page("Réglages")
        # Aucun bouton « Enregistrer ». Chaque changement s'applique et
        # s'enregistre de lui-même, comme dans les réglages du système : un
        # bouton en pied de formulaire descend sous le bord de la fenêtre dès
        # qu'on la réduit — constaté, on changeait un réglage, aucun bouton
        # n'était visible, et rien n'était écrit. Un bouton qu'il faut aller
        # chercher pour valider n'a pas sa place ici.
        entete = tk.Frame(page, bg=self.couleurs.carte)
        entete.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        entete.columnconfigure(0, weight=1)
        self.mot_reglages = self._texte(
            entete, "Chaque changement s'applique et s'enregistre aussitôt.",
            taille=11, pale=True)
        self.mot_reglages.grid(row=0, column=0, sticky="w")
        dedans = self._zone_defilante(page)

        rang = 0
        rang = self._bloc(dedans, rang, "Micro", "Celui que Greffier prend au démarrage.")
        # « Micro » sous un bloc déjà intitulé « Micro » ne dit rien de plus :
        # l'intitulé de la ligne nomme ce qu'on choisit, l'appareil.
        self.reglage_micro = self._liste_deroulante(dedans, rang, "Appareil")
        rang += 1

        rang = self._bloc(dedans, rang, "Participants",
                          "Le nombre de personnes autour de la table, si tu le connais.")
        self.reglage_participants = self._liste_deroulante(dedans, rang, "Personnes",
                                                          largeur=232)
        rang += 1

        rang = self._bloc(dedans, rang, "Transcription",
                          "Le modèle de la transcription définitive, faite après la réunion.")
        self.reglage_modele = self._liste_deroulante(dedans, rang, "Modèle")
        rang += 1
        self.reglage_langue = self._liste_deroulante(dedans, rang, "Langue", largeur=232)
        rang += 1

        rang = self._bloc(dedans, rang, "Compte Claude",
                          "C'est lui qui rédige : sans session ouverte, tout marche "
                          "sauf le compte rendu.")
        self.mot_compte = self._texte(dedans, "", taille=11)
        self.mot_compte.grid(row=rang, column=0, columnspan=2, sticky="w", pady=(0, 5))
        rang += 1
        boutons = tk.Frame(dedans, bg=self.couleurs.carte)
        boutons.grid(row=rang, column=0, columnspan=2, sticky="w", pady=(0, 2))
        # Une seule action principale, dont l'intitulé suit l'état : proposer
        # « Se connecter » à qui l'est déjà laisse croire que la session n'est
        # pas vue. Aucun bouton « Actualiser » : l'état se relit tout seul
        # chaque fois que l'onglet s'affiche.
        self.bouton_session = Bouton(boutons, "Se connecter", self._session_claude,
                                     self.couleurs, largeur=150, hauteur=32)
        self.bouton_session.pack(side="left", padx=(0, 8))
        self.bouton_maj = Bouton(boutons, "Mettre à jour", self._mettre_a_jour_claude,
                                 self.couleurs, largeur=132, hauteur=32)
        self.bouton_maj.pack(side="left")
        rang += 1

        rang = self._bloc(dedans, rang, "Rédaction du compte rendu",
                          "Qui rédige, avec quel modèle, et à qui le document part.")
        self.reglage_redacteur = self._liste_deroulante(dedans, rang, "Rédacteur")
        rang += 1
        self.reglage_modele_redaction = self._liste_deroulante(dedans, rang, "Modèle")
        rang += 1
        self.reglage_destinataire = self._saisie(dedans, rang, "Destinataire", 34)
        rang += 1

        rang = self._bloc(dedans, rang, "Pendant la réunion",
                          "Le fil affiché en direct. Un second modèle tourne : c'est son coût.")
        self.direct_actif = tk.BooleanVar(value=self.config.direct.actif)
        self.case_direct = case = tk.Checkbutton(
            dedans, text="Afficher ce qui se dit pendant la réunion",
            variable=self.direct_actif, bg=self.couleurs.carte, fg=self.couleurs.encre,
            activebackground=self.couleurs.carte, activeforeground=self.couleurs.encre,
            selectcolor=self.couleurs.fond, font=police(12), anchor="w",
            highlightthickness=0, borderwidth=0,
            # Sans ces deux-là, macOS dessine une case bleue système, seule
            # touche de couleur de la fenêtre et hors de la palette.
            disabledforeground=self.couleurs.calme, cursor="arrow",
        )
        case.grid(row=rang, column=0, columnspan=2, sticky="w", pady=(1, 3))
        rang += 1
        self.reglage_periode = self._liste_deroulante(dedans, rang, "Tranche")
        rang += 1

        rang = self._bloc(dedans, rang, "Apparence", "")
        self.reglage_theme = self._liste_deroulante(dedans, rang, "Thème")
        rang += 1

        self._brancher_les_reglages()
        # Relire à l'affichage plutôt que d'offrir un bouton : la session peut
        # avoir été ouverte dans le terminal entre-temps, et l'événement <Map>
        # est justement émis quand la page revient au premier plan.
        page.bind("<Map>", lambda _e: self._dire_le_compte())
        # Les enfants interceptent la molette avant leur parent : sans cette
        # passe, la roue ne fait rien dès que le curseur est sur une étiquette.
        self._ecouter_la_molette(dedans)
        self._garnir_les_reglages()
        self._dire_le_compte()

    def _brancher_les_reglages(self) -> None:
        """Fait de chaque changement un enregistrement.

        Les listes et la case enregistrent au choix. Les deux champs de saisie
        enregistrent quand on les quitte ou qu'on valide, jamais à la frappe :
        écrire un fichier à chaque lettre d'une adresse courriel produirait une
        vingtaine de fichiers et autant de sauvegardes, dont la plupart avec une
        adresse incomplète.
        """
        # Les listes préviennent elles-mêmes (`sur_choix`, posé à la création) :
        # seul le rédacteur demande un traitement de plus, sa liste de modèles
        # dépendant de lui.
        self.reglage_redacteur.sur_choix = lambda _clef: self._redacteur_choisi()
        self.case_direct.configure(command=self._enregistrer_reglages)
        # Le seul champ libre qui reste : une adresse courriel ne se choisit pas
        # dans une liste. Il enregistre quand on le quitte ou qu'on valide.
        self.reglage_destinataire.bind("<FocusOut>", lambda _e: self._enregistrer_reglages())
        self.reglage_destinataire.bind("<Return>", lambda _e: self._enregistrer_reglages())

    def _redacteur_choisi(self, _evenement: Any = None) -> None:
        """Changer de rédacteur change la liste des modèles, puis enregistre."""
        self._accorder_le_modele_de_redaction()
        self._enregistrer_reglages()

    def _ecouter_la_molette(self, parent: tk.Misc) -> None:
        for enfant in parent.winfo_children():
            # Les listes déroulantes gardent la molette pour elles : elle y
            # change la valeur, ce qui est le comportement attendu.
            if not isinstance(enfant, ttk.Combobox):
                enfant.bind("<MouseWheel>", self._molette_reglages)
            self._ecouter_la_molette(enfant)

    def _zone_defilante(self, page: tk.Frame) -> tk.Frame:
        """Une zone qui défile, et rend le cadre où poser le contenu.

        Un formulaire est plus haut que la fenêtre dès qu'on réduit celle-ci, et
        Tk ne défile pas de lui-même : sans cela, les derniers réglages sont
        simplement hors d'atteinte, sans rien qui l'indique — constaté, la
        rédaction et l'apparence étaient invisibles et inaccessibles.

        `Canvas` plutôt qu'un `Frame` : c'est le seul conteneur Tk qui sache
        montrer une fenêtre plus grande que lui. La largeur du contenu est
        recalée sur celle du canevas, sans quoi la grille se tasserait à gauche
        au lieu d'occuper la carte.
        """
        c = self.couleurs
        page.rowconfigure(0, weight=0)   # la ligne d'état, en tête
        page.rowconfigure(1, weight=1)   # la zone qui défile
        page.columnconfigure(0, weight=1)
        toile = tk.Canvas(page, bg=c.carte, highlightthickness=0, borderwidth=0)
        toile.grid(row=1, column=0, sticky="nsew")
        ascenseur = Defileur(page, c, toile.yview)
        ascenseur.grid(row=1, column=1, sticky="ns", padx=(6, 0))
        toile.configure(yscrollcommand=ascenseur.set)

        contenu = tk.Frame(toile, bg=c.carte)
        fenetre = toile.create_window((0, 0), window=contenu, anchor="nw")
        contenu.columnconfigure(1, weight=1)

        def au_contenu(_evenement: Any = None) -> None:
            toile.configure(scrollregion=toile.bbox("all"))

        def a_la_toile(evenement: Any) -> None:
            toile.itemconfigure(fenetre, width=evenement.width)
            au_contenu()

        contenu.bind("<Configure>", au_contenu)
        toile.bind("<Configure>", a_la_toile)

        def molette(evenement: Any) -> None:
            # Rien à faire défiler : ne pas capturer la molette, sinon la
            # fenêtre paraît figée alors que tout est déjà visible.
            haut, bas = toile.yview()
            if haut <= 0.0 and bas >= 1.0:
                return
            # macOS livre un delta par crans, X11 par boutons 4/5 (delta ±120).
            pas = -evenement.delta if platform.system() == "Darwin" else -evenement.delta // 120
            toile.yview_scroll(int(pas), "units")

        # Liée à la toile et à ses descendants : la molette doit agir où qu'on
        # ait le curseur dans le formulaire, pas seulement sur le fond.
        for cible in (toile, contenu):
            cible.bind("<MouseWheel>", molette)
        self._molette_reglages = molette
        # Gardées : c'est par elles qu'on mesure ce que le formulaire demande et
        # ce que la fenêtre offre, sans comparer des pixels à l'œil.
        self.reglages_toile = toile
        self.reglages_contenu = contenu
        return contenu

    def _bloc(self, parent: tk.Frame, rang: int, titre: str, sous_titre: str) -> int:
        """Un intitulé de bloc. Rend le rang suivant, pour ne pas les compter à la main."""
        haut = 0 if rang == 0 else 13
        self._texte(parent, titre, taille=12, gras=True).grid(
            row=rang, column=0, columnspan=2, sticky="w", pady=(haut, 1))
        if not sous_titre:
            return rang + 1
        self._texte(parent, sous_titre, taille=11, pale=True).grid(
            row=rang + 1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        return rang + 2

    def _liste_deroulante(self, parent: tk.Frame, rang: int, intitule: str,
                          largeur: int = 392) -> Liste:
        self._texte(parent, intitule, taille=11, pale=True).grid(
            row=rang, column=0, sticky="w", padx=(0, 12), pady=3)
        liste = Liste(parent, self.couleurs, largeur=largeur,
                      sur_choix=lambda _clef: self._enregistrer_reglages())
        liste.grid(row=rang, column=1, sticky="w", pady=3)
        return liste

    def _saisie(self, parent: tk.Frame, rang: int, intitule: str, largeur: int) -> tk.Entry:
        self._texte(parent, intitule, taille=11, pale=True).grid(
            row=rang, column=0, sticky="w", padx=(0, 12), pady=2)
        champ = self._champ(parent, largeur)
        champ.grid(row=rang, column=1, sticky="w", ipady=4, ipadx=4, pady=2)
        return champ

    def _garnir_les_reglages(self) -> None:
        """Remplit le formulaire depuis la configuration en vigueur."""
        from greffier.assistant import MODELES_CLAUDE

        self.reglage_micro.garnir(list(self._micros_reglables()), self.config.audio.micro)
        self.reglage_modele.garnir(list(self._modeles_presents()),
                                   self.config.transcription.modele)
        self.reglage_langue.garnir(list(self.LANGUES), self.config.transcription.langue)
        self.reglage_redacteur.garnir(list(self.MOTEURS_REDACTION),
                                      self.config.compte_rendu.moteur)
        self._modeles_claude = tuple(MODELES_CLAUDE)
        self._accorder_le_modele_de_redaction()
        self.reglage_destinataire.delete(0, "end")
        self.reglage_destinataire.insert(0, self.config.compte_rendu.destinataire)
        self.reglage_periode.garnir(list(self.PERIODES_DIRECT),
                                    f"{self.config.direct.periode:.1f}")
        self.reglage_theme.garnir(list(self.THEMES), self.config.apparence.theme)
        personnes = self.config.locuteurs.personnes
        self.reglage_participants.garnir(list(self.PARTICIPANTS),
                                         str(personnes) if personnes else "")

    def _micros_reglables(self) -> tuple[tuple[str, str], ...]:
        """Les micros branchés, plus le mode automatique — dont la valeur est vide.

        Vide et non « automatique » : c'est ce que la configuration attend, et
        c'est le réglage qui laisse l'écoute décider au démarrage plutôt que de
        promettre un micro qu'un bouton de sourdine écarterait.
        """
        from greffier.composition import listeur

        noms: list[str] = []
        try:
            materiel = listeur(self.config).lire()
        except (OSError, RuntimeError):
            materiel = None
        if materiel is not None:
            noms = [p.nom for p in materiel.micros
                    if not p.uid.startswith("com.reunions.")
                    and "blackhole" not in p.nom.lower()]
        voulu = self.config.audio.micro
        if voulu and voulu not in noms:
            # Un micro réglé mais débranché doit rester visible et sélectionné,
            # sinon enregistrer les réglages l'effacerait sans le dire.
            noms.append(f"{voulu}")
        return (("", "Automatique — le mieux entendu"),
                *((nom, nom) for nom in noms))

    def _modeles_presents(self) -> tuple[tuple[str, str], ...]:
        dossier = self.config.chemins.modeles
        presents = tuple(
            (clef, libelle) for clef, libelle in self.MODELES_TRANSCRIPTION
            if (dossier / f"ggml-{clef}.bin").exists()
        )
        if presents:
            return presents
        # Rien sur le disque : ne pas rendre une liste vide, qui laisserait
        # croire que le réglage est cassé plutôt qu'un modèle manquant.
        return ((self.config.transcription.modele,
                 f"{self.config.transcription.modele} — aucun modèle trouvé sur le disque"),)

    def _accorder_le_modele_de_redaction(self) -> None:
        """La liste des modèles suit le rédacteur choisi.

        Un alias Claude Code n'a aucun sens pour Ollama, et l'inverse non plus :
        proposer les deux ensemble laisserait enregistrer une combinaison qui
        échouerait à la première rédaction.
        """
        moteur = self.reglage_redacteur.valeur()
        if moteur == "claude":
            choix = self._modeles_claude
        elif moteur == "ollama":
            from greffier.assistant import _modeles_ollama

            presents = _modeles_ollama()
            choix = tuple((m, m) for m in presents) or (("qwen3:8b", "qwen3:8b — à télécharger"),)
        else:
            choix = (("", "Sans objet : aucun rédacteur"),)
        self.reglage_modele_redaction.garnir(
            list(choix), self.config.compte_rendu.modele or (choix[0][0] if choix else ""))
        self.reglage_modele_redaction.activer(moteur != "aucun")

    def _dire_le_compte(self) -> None:
        """Affiche l'état du compte, et accorde les boutons à cet état."""
        from greffier import diagnostic

        if not diagnostic.claude_installe():
            self.mot_compte.configure(
                text="Claude Code n'est pas installé : aucun compte rendu ne pourra "
                     "être rédigé.",
                fg=self.couleurs.ambre)
            self.bouton_session.intituler("Installer")
            self.bouton_maj.activer(False)
            return
        self.bouton_maj.activer(True)
        compte = diagnostic.compte_claude()
        version = diagnostic.claude_version()
        if compte is None:
            self.mot_compte.configure(
                text=f"Claude Code {version} — aucune session ouverte.",
                fg=self.couleurs.ambre)
            self.bouton_session.intituler("Se connecter")
            return
        formule = f" · {compte.formule}" if compte.formule else ""
        self.mot_compte.configure(text=f"Connecté · {compte}{formule} · "
                                       f"Claude Code {version}",
                                  fg=self.couleurs.encre)
        self.bouton_session.intituler("Changer de compte")

    def _session_claude(self) -> None:
        """Ouvre un terminal sur « claude », où la session se règle.

        La connexion est interactive : elle ouvre un navigateur et attend un
        code. Rien de tout cela ne se pilote depuis une fenêtre Tk, et il ne
        faut pas essayer — c'est le terminal qui sait le faire.

        Un fichier `.command` ouvert par `open` plutôt qu'un `osascript` qui
        pilote Terminal : le second réclamerait l'autorisation
        « Automatisation », donc un dialogue système de plus, pour le même
        résultat.
        """
        import tempfile

        from greffier import diagnostic

        if not diagnostic.claude_installe():
            commande = diagnostic.COMMANDE_INSTALLER_CLAUDE.get(platform.system(), "")
            self.mot_compte.configure(text=f"À installer : {commande}",
                                      fg=self.couleurs.ambre)
            return
        if platform.system() != "Darwin":
            self.mot_compte.configure(
                text="Lance « claude » dans un terminal, puis reviens ici.",
                fg=self.couleurs.ambre)
            return
        deja = diagnostic.compte_claude() is not None
        # « /login » ne sert qu'à changer de compte : sur une session absente,
        # « claude » tout court propose déjà la connexion, et une commande
        # passée à un outil non connecté serait avalée.
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
            fg=self.couleurs.encre_pale)

    def _mettre_a_jour_claude(self) -> None:
        """Lance « claude update », dans un fil : il télécharge."""
        from greffier import diagnostic

        if not diagnostic.claude_installe():
            self._dire_le_compte()
            return
        avant = diagnostic.claude_version()
        self.mot_compte.configure(text=f"Mise à jour depuis {avant}…",
                                  fg=self.couleurs.encre_pale)

        def faire(_dire: Callable[[str], None]) -> str:
            fait = subprocess.run(["claude", "update"], capture_output=True,
                                  text=True, check=False, timeout=600)
            sortie = (fait.stdout + fait.stderr).splitlines()
            lignes = [ligne for ligne in sortie if ligne.strip()]
            return lignes[-1][:120] if lignes else ""

        def fini(resultat: Any, souci: Exception | None) -> None:
            if souci is not None:
                self.mot_compte.configure(text=f"Mise à jour impossible : {souci}",
                                          fg=self.couleurs.ambre)
                return
            apres = diagnostic.claude_version()
            if apres and apres != avant:
                self.mot_compte.configure(text=f"Mis à jour : {avant} → {apres}",
                                          fg=self.couleurs.encre)
            else:
                self.mot_compte.configure(text=resultat or f"Déjà à jour ({avant}).",
                                          fg=self.couleurs.encre_pale)

        self._lancer(Travail(intitule="Mise à jour de Claude Code", faire=faire, fini=fini))

    def _appliquer_le_theme(self, theme: str, mot: str = "") -> None:
        """Repeint la fenêtre sans la relancer.

        Les couleurs sont lues à la construction de chaque composant — plusieurs
        les dessinent eux-mêmes sur un canevas — donc les changer demande de
        reconstruire l'intérieur de la fenêtre. Ce qui porte l'état ne bouge
        pas : la capture vit dans un processus séparé, la veille et le direct
        aussi, et le fil affiché se relit du journal. Seuls les composants sont
        refaits.

        Les boucles d'animation déjà armées se taisent d'elles-mêmes quand leur
        canevas disparaît (voir `Vumetre._pas`).
        """
        self.couleurs = palette(theme)
        self.racine.configure(bg=self.couleurs.fond)
        self._styler_listes()
        for enfant in self.racine.winfo_children():
            enfant.destroy()
        self._phase_peinte = None
        self._micros_connus = ()
        self._fil_reunion = ""
        self._fil_position = 0
        self._construire()
        self.onglets.montrer("Réglages")
        # La ligne d'état est un composant neuf : sans cela, la confirmation
        # écrite juste avant le repeint disparaîtrait avec l'ancienne.
        if mot:
            self.mot_reglages.configure(text=mot)
        with contextlib.suppress(OSError, ValueError, tk.TclError):
            self._peindre(self.machine.lire())

    def _enregistrer_reglages(self) -> None:
        """Écrit `config.toml`, puis applique ce qui peut l'être sans relancer."""
        from greffier import reglages

        moteur = self.reglage_redacteur.valeur()
        theme_avant = self.config.apparence.theme
        neuf = self.config.model_copy(deep=True)
        neuf.audio.micro = self.reglage_micro.valeur()
        neuf.transcription.modele = self.reglage_modele.valeur()
        neuf.transcription.langue = self.reglage_langue.valeur()
        neuf.compte_rendu.moteur = moteur
        neuf.compte_rendu.modele = ("" if moteur == "aucun"
                                    else self.reglage_modele_redaction.valeur())
        neuf.compte_rendu.destinataire = self.reglage_destinataire.get().strip()
        neuf.direct.actif = bool(self.direct_actif.get())
        neuf.direct.periode = float(self.reglage_periode.valeur())
        neuf.apparence.theme = self.reglage_theme.valeur()
        annonce = self.reglage_participants.valeur()
        neuf.locuteurs.personnes = int(annonce) if annonce else None

        # `neuf` est une copie de la configuration en vigueur : le vocabulaire,
        # les mots qui ne sont jamais des prénoms et les réglages SMTP — que la
        # fenêtre ne propose pas — y sont déjà, et sont réécrits tels quels.
        try:
            reglages.sauver(neuf)
        except OSError as souci:
            self.mot_reglages.configure(text=f"Échec de l'enregistrement : {souci}")
            return

        self.config = neuf
        mots = [f"Enregistré · {datetime.now().strftime('%H:%M:%S')}"]
        if neuf.compte_rendu.moteur == "claude":
            mots.append(f"rédacteur {neuf.compte_rendu.modele_effectif}")
        mot = " · ".join(mots)
        self.mot_reglages.configure(text=mot)
        if neuf.apparence.theme != theme_avant:
            # Repeindre tout de suite : un thème qui attend « le prochain
            # lancement » donne l'impression que le réglage n'a rien fait.
            # Après le retour de l'événement, jamais pendant : la liste
            # déroulante qui vient d'être choisie serait détruite sous Tk, au
            # milieu du traitement de son propre événement.
            self.racine.after(0, lambda: self._appliquer_le_theme(neuf.apparence.theme, mot))

    # ------------------------------------------------------------------ micros

    def _charger_micros(self) -> None:
        """Propose les micros réellement branchés, celui de la config en tête."""
        from greffier.composition import listeur

        try:
            materiel = listeur(self.config).lire()
        except (OSError, RuntimeError):
            materiel = None
        noms: list[str] = []
        if materiel is not None:
            noms = [
                p.nom for p in materiel.micros
                if not p.uid.startswith("com.reunions.")
                and "blackhole" not in p.nom.lower()
            ]
        # « Automatique » ne nomme personne : le choix se fait au démarrage, en
        # écoutant chaque micro. Nommer ici le candidat retenu par sa seule forme
        # promettait un micro que l'écoute écarte ensuite — un casque branché
        # dont le bouton de sourdine est enfoncé, par exemple.
        # La clef vide veut dire « automatique » : le choix se fait au démarrage,
        # en écoutant chaque micro. Nommer ici le candidat retenu sur sa seule
        # forme promettait un micro que l'écoute écarte ensuite — un casque
        # branché dont le bouton de sourdine est enfoncé, par exemple.
        propositions = (("", "Automatique — le mieux entendu"),
                        *((nom, nom) for nom in noms))
        if propositions == self._micros_connus:
            # Rien n'a bougé : regarnir refermerait le menu sous le curseur de
            # qui est en train d'y choisir.
            return
        self._micros_connus = propositions
        choisi = self.micro.valeur()
        voulu = self.config.audio.micro
        connus = [clef for clef, _ in propositions]
        garde = choisi if choisi in connus else (voulu if voulu in connus else "")
        self.micro.garnir(list(propositions), garde)

    # ---------------------------------------------------------- rafraîchissement

    def _rafraichir(self) -> None:
        # L'état est illisible l'instant d'une écriture atomique : on repasse.
        with contextlib.suppress(OSError, ValueError):
            self._peindre(self.machine.lire())
        self._vider_messages()
        self.racine.after(PERIODE_MS, self._rafraichir)

    def _suivre_les_micros(self) -> None:
        """Tient la liste des micros à jour, sans qu'on ait à rouvrir la fenêtre.

        Brancher ou retirer un casque doit se voir tout de suite : c'est le
        moment où l'on vérifie qu'on a choisi le bon, juste avant de démarrer.
        """
        if self._phase_peinte in (None, Phase.REPOS):
            with contextlib.suppress(OSError, RuntimeError):
                self._charger_micros()
        self.racine.after(PERIODE_MICROS_MS, self._suivre_les_micros)

    def _respirer(self) -> None:
        """Fait pulser le point rouge pendant l'enregistrement.

        Un fondu vers la couleur de la carte plutôt qu'un vrai canal alpha :
        Tk ne sait pas dessiner de transparence sur un canvas, mais un point
        qui se rapproche du fond produit le même effet à l'œil.
        """
        if self._phase_peinte is Phase.ENREGISTREMENT:
            c = self.couleurs
            part = (math.sin(2 * math.pi * time.time() / PULSATION_S) + 1) / 2
            self.pastille.itemconfigure(self._point, fill=_degrade(c.actif, c.carte, part * 0.65))
        self.racine.after(PULSATION_MS, self._respirer)

    def _peindre(self, etat: Any) -> None:
        c = self.couleurs
        if etat.phase is not self._phase_peinte:
            precedente = self._phase_peinte
            self._phase_peinte = etat.phase
            self._montrer_commandes(etat.phase)
            if etat.phase is Phase.REPOS:
                # Le matériel a pu changer pendant la réunion précédente.
                self._charger_micros()
            if etat.phase is Phase.ENREGISTREMENT and precedente is not None:
                # La réunion commence : c'est le fil qu'on veut sous les yeux,
                # pas la liste des réunions passées.
                self.onglets.montrer("En direct")

        actif = etat.phase is Phase.ENREGISTREMENT
        en_pause = etat.phase is Phase.PAUSE
        if not actif:
            # Pendant l'enregistrement, c'est « _respirer » qui tient le point :
            # l'écraser ici quatre fois par seconde casserait son fondu.
            self.pastille.itemconfigure(
                self._point, fill=c.ambre if en_pause else c.calme
            )
        self.titre.configure(text=etat.nom or "Prêt")
        self.detail.configure(text=etat.message or "Aucun enregistrement en cours.")
        self.chrono.configure(text=horloge(etat.secondes) if actif or en_pause else "")

        self._suivre_le_direct(etat)

        if actif and etat.morceaux:
            self._peindre_niveaux(relever(etat.morceaux[-1]))
        else:
            self.vu_toi.montrer(0)
            self.vu_autres.montrer(0)
            self.qui.configure(text="en pause" if en_pause else "",
                               fg=c.ambre if en_pause else c.vert)

    def _peindre_niveaux(self, releve: Releve | None) -> None:
        if releve is None:
            self.qui.configure(text="en attente du son…", fg=self.couleurs.encre_pale)
            return
        self.vu_toi.montrer(releve.micro_part)
        self.vu_autres.montrer(releve.systeme_part)
        self.qui.configure(text=_LIBELLES_VOIX[releve.qui], fg=self.couleurs.vert)

    def _vider_messages(self) -> None:
        for travail in list(self.travaux):
            while not travail.messages.empty():
                self.etat_bas.configure(text=travail.messages.get_nowait())

    # ------------------------------------------------------------------ actions

    def _demarrer(self) -> None:
        from greffier.cli import _lancer_direct, _lancer_veille, _preparer_capture

        # La clef vide — « automatique » — laisse le domaine décider, et la
        # veille suivre.
        choisi = self.micro.valeur()
        if choisi:
            self.config.audio.micro = choisi
        try:
            # Le poste est mis dans le meilleur état possible sans rien demander :
            # micro réellement branché, sortie système vers la boucle de capture,
            # gain relevé s'il est trop bas.
            precedente = _preparer_capture(self.config)
            self.machine.demarrer("reunion", sortie_precedente=precedente)
            _lancer_veille(self.config, None)
            # Sans cet appel, l'onglet « En direct » reste vide : c'est lui qui
            # lance le processus qui transcrit et publie au fil de l'eau.
            _lancer_direct(self.config, None)
        except (RuntimeError, FileNotFoundError) as souci:
            messagebox.showerror("Greffier", str(souci))

    def _suspendre(self) -> None:
        try:
            self.machine.suspendre()
        except RuntimeError as souci:
            messagebox.showerror("Greffier", str(souci))

    def _relancer(self) -> None:
        try:
            self.machine.relancer()
        except RuntimeError as souci:
            messagebox.showerror("Greffier", str(souci))

    def _fermer(self) -> None:
        """Ferme la fenêtre — en terminant d'abord la réunion, s'il y en a une.

        La réunion est arrêtée proprement (audio recollé, sortie système
        rendue), pas traitée : quitter n'est pas demander un compte rendu, et
        la réunion reste dans la liste pour être traitée plus tard. Les
        processus détachés (veille, direct) s'arrêtent d'eux-mêmes en voyant
        l'enregistrement finir — c'est leur contrat, pas besoin de les tuer.
        """
        phase = None
        with contextlib.suppress(OSError, ValueError):
            phase = self.machine.lire().phase
        if phase in (Phase.ENREGISTREMENT, Phase.PAUSE):
            if not messagebox.askyesno(
                "Greffier",
                "Une réunion est en cours d'enregistrement.\n"
                "La terminer proprement et quitter ?",
            ):
                return
            from greffier.cli import _rendre_la_sortie

            with contextlib.suppress(RuntimeError):
                etat = self.machine.arreter()
                _rendre_la_sortie(etat.sortie_precedente)
        self.racine.destroy()

    def _terminer(self) -> None:
        from greffier.cli import _rendre_la_sortie

        try:
            etat = self.machine.arreter()
        except RuntimeError as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        _rendre_la_sortie(etat.sortie_precedente)
        audio = etat.audio
        if audio is None:
            return
        self._lancer(Travail(
            intitule="traitement",
            faire=self._chaine(audio, etat.evenements),
            fini=lambda resultat, souci: self._traitement_fini(audio, resultat, souci),
        ))

    def _chaine(
        self, audio: Path, evenements: list[str] | None = None
    ) -> Callable[[Callable[[str], None]], Any]:
        """Prépare l'exécution de la chaîne, l'avancement remonté à l'écran."""

        def faire(dire: Callable[[str], None]) -> Any:
            from greffier.composition import assembler

            chaine = assembler(self.config)
            publieur = chaine.journal

            def publier(phase: str, message: str = "") -> None:
                dire(message or phase)
                if publieur is not None:
                    with contextlib.suppress(OSError, ValueError):
                        publieur.publier(phase, message)

            chaine.journal = type("Journal", (), {"publier": staticmethod(publier)})()
            # Un destinataire renseigné *est* la demande d'envoi. Attendre un
            # clic de plus, c'est demander deux fois la même chose, et le but de
            # l'outil est bien de produire un compte rendu et de l'envoyer.
            return chaine.executer(
                audio,
                envoyer=bool(self.config.compte_rendu.destinataire),
                evenements_materiel=evenements,
            )

        return faire

    def _traitement_fini(self, audio: Path, resultat: Any, souci: Exception | None) -> None:
        self._charger_reunions()
        if souci is not None:
            self.etat_bas.configure(text=f"Échec : {souci}")
            messagebox.showerror("Greffier", str(souci))
            return
        for avertissement in getattr(resultat, "avertissements", []):
            self._dire("note", avertissement)
        self.etat_bas.configure(text="Compte rendu prêt.")
        self._choisir(audio.stem)
        self.onglets.montrer("Conversation")
        self._proposer_la_suite(audio.stem, resultat)

    def _proposer_la_suite(self, identifiant: str, resultat: Any) -> None:
        """Ce que Greffier demande de lui-même, une fois le compte rendu écrit.

        Le but de l'outil est de produire un compte rendu et de l'envoyer : la
        question est posée à chaque fois, plutôt que laissée à l'initiative de
        qui aurait pensé à aller la chercher.
        """
        self._dire("greffier", f"Le compte rendu de « {identifiant} » est prêt.")
        significatives: dict[str, float] = getattr(resultat, "voix_significatives", dict)()
        noms: dict[str, str] = getattr(resultat, "noms", {})
        sans_nom = [voix for voix in significatives if voix not in noms]
        if sans_nom:
            self._dire(
                "greffier",
                f"{len(sans_nom)} voix ne portent pas encore de nom. L'onglet Voix "
                "permet d'écouter dix secondes et de les nommer : elles seront "
                "reconnues seules aux réunions suivantes.",
            )
        destinataire = self.config.compte_rendu.destinataire
        if destinataire and getattr(resultat, "envoye", False):
            self._dire("greffier", f"Envoyé à {destinataire}.")
        elif destinataire:
            self._dire("greffier", f"L'envoi à {destinataire} n'a pas abouti : "
                                   "onglet Réunions, « Envoyer par courriel ».")
        else:
            self._dire("greffier", "Aucun destinataire n'est configuré, le compte rendu "
                                   "reste sur le disque. Renseigne "
                                   "compte_rendu.destinataire pour qu'il puisse partir.")

    # -------------------------------------------------------- fils d'exécution

    def _lancer(self, travail: Travail) -> None:
        self.travaux.append(travail)
        self.etat_bas.configure(text=f"{travail.intitule} en cours…")

        def courir() -> None:
            resultat: Any = None
            souci: Exception | None = None
            try:
                resultat = travail.faire(travail.messages.put)
            except Exception as attrape:  # noqa: BLE001 - remonté à l'interface
                souci = attrape
            # Repasser sur le fil de l'interface : Tk n'est pas réentrant.
            self.racine.after(0, lambda: self._achever(travail, resultat, souci))

        threading.Thread(target=courir, daemon=True).start()

    def _achever(self, travail: Travail, resultat: Any, souci: Exception | None) -> None:
        if travail in self.travaux:
            self.travaux.remove(travail)
        # La ligne du bas annonce « … en cours… » au lancement : plus rien ne
        # l'effaçait. Constaté à l'usage, « Mise à jour de Claude Code en
        # cours… » restait affiché indéfiniment après la fin de la mise à jour,
        # laissant croire qu'elle tournait encore. Seule la dernière tâche
        # efface : deux traitements simultanés ne doivent pas se couper la
        # parole.
        if not self.travaux:
            self.etat_bas.configure(text="")
        travail.fini(resultat, souci)

    # ------------------------------------------------------------------ listes

    def _selection(self) -> str | None:
        """L'identifiant technique de la réunion choisie.

        La colonne affiche le sujet déduit du compte rendu ; l'identifiant vit
        sur la ligne elle-même, pour que renommer l'affichage ne casse rien.
        """
        choix = self.liste.selection()
        return str(choix[0]) if choix else None

    def _choisir(self, identifiant: str) -> None:
        """Sélectionne une réunion, pour que les autres onglets suivent."""
        if self.liste.exists(identifiant):
            self.liste.selection_set(identifiant)
            self.liste.see(identifiant)
            self._charger_voix()

    def _charger_reunions(self) -> None:
        from greffier.application.nommer import voix_a_nommer

        garde = self._selection()
        for ligne in self.liste.get_children():
            self.liste.delete(ligne)
        for identifiant in self.depot.lister():
            try:
                detail = self.depot.lire(identifiant)
            except (OSError, ValueError):
                continue
            compte_rendu = self.config.chemins.comptes_rendus / f"{identifiant}.md"
            # Les voix significatives, pas les groupes bruts de la segmentation :
            # « 118 » ne dit rien à personne, « 4 » est un nombre de participants.
            self.liste.insert("", "end", iid=identifiant, values=(
                sujet_lisible(identifiant, compte_rendu),
                len(voix_a_nommer(detail)),
                sum(len(r.texte.split()) for r in detail.repliques),
                "oui" if compte_rendu.exists() else "non",
            ))
        if garde:
            self._choisir(garde)

    def _charger_voix(self) -> None:
        from greffier.application.nommer import voix_a_nommer

        for ligne in self.voix.get_children():
            self.voix.delete(ligne)
        identifiant = self._selection()
        if identifiant is None:
            return
        try:
            detail = self.depot.lire(identifiant)
        except (OSError, ValueError):
            return
        for candidate in voix_a_nommer(detail):
            self.voix.insert("", "end", values=(
                candidate.voix,
                f"{candidate.duree / 60:.1f} min",
                f"{candidate.part * 100:.0f} %",
                candidate.nom
                or (f"≈ {candidate.proposition}" if candidate.proposition else "à nommer"),
            ))

    # ----------------------------------------------------------- actions liste

    def _traiter_selection(self) -> None:
        identifiant = self._selection()
        if identifiant is None:
            self.etat_bas.configure(text="Choisis une réunion dans la liste.")
            return
        try:
            audio = self.depot.lire(identifiant).audio
        except (OSError, ValueError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        self._lancer(Travail(
            intitule=f"traitement de {identifiant}",
            faire=self._chaine(audio),
            fini=lambda resultat, souci: self._traitement_fini(audio, resultat, souci),
        ))

    def _ouvrir_compte_rendu(self) -> None:
        import subprocess

        identifiant = self._selection()
        if identifiant is None:
            self.etat_bas.configure(text="Choisis une réunion dans la liste.")
            return
        chemin = self.config.chemins.comptes_rendus / f"{identifiant}.md"
        if not chemin.exists():
            messagebox.showinfo("Greffier", "Aucun compte rendu pour cette réunion.")
            return
        ouvreur = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([ouvreur, str(chemin)], check=False)

    def _envoyer_selection(self) -> None:
        from greffier.adaptateurs import gabarit_courriel
        from greffier.composition import _expediteur

        identifiant = self._selection()
        if identifiant is None:
            self.etat_bas.configure(text="Choisis une réunion dans la liste.")
            return
        chemin = self.config.chemins.comptes_rendus / f"{identifiant}.md"
        if not chemin.exists():
            messagebox.showinfo("Greffier", "Traite d'abord la réunion.")
            return
        compte_rendu = chemin.read_text(encoding="utf-8")
        objet = gabarit_courriel.sujet(compte_rendu, f"Compte rendu : {identifiant}")
        cible = self.config.compte_rendu.destinataire
        if not cible:
            messagebox.showinfo(
                "Greffier",
                "Aucun destinataire configuré. Renseigne compte_rendu.destinataire.",
            )
            return
        if not messagebox.askyesno("Greffier", f"Envoyer à {cible} ?\n\n{objet}"):
            return
        expediteur = _expediteur(self.config, exiger_destinataire=False)
        if expediteur is None:
            messagebox.showerror("Greffier", "Aucun moyen d'envoi configuré.")
            return

        def faire(dire: Callable[[str], None]) -> Any:
            dire(f"envoi à {cible}…")
            expediteur.envoyer(cible, objet, compte_rendu, [])
            return cible

        self._lancer(Travail(intitule="envoi", faire=faire,
                             fini=lambda _r, souci: self._envoi_fini(cible, souci)))

    def _envoi_fini(self, cible: str, souci: Exception | None) -> None:
        if souci is not None:
            messagebox.showerror("Greffier", str(souci))
            return
        self.etat_bas.configure(text=f"Envoyé à {cible}")
        self._dire("greffier", f"Compte rendu envoyé à {cible}.")

    # ------------------------------------------------------------ actions voix

    def _voix_selectionnee(self) -> str | None:
        choix = self.voix.selection()
        return str(self.voix.item(choix[0], "values")[0]) if choix else None

    def _nommer(self) -> None:
        from greffier.composition import nommage

        identifiant, voix = self._selection(), self._voix_selectionnee()
        nom = self.champ_nom.get().strip()
        if not identifiant:
            messagebox.showinfo("Greffier", "Choisis une réunion dans l'onglet Réunions.")
            return
        if not voix:
            messagebox.showinfo("Greffier", "Choisis une voix dans la liste.")
            return
        if not nom:
            messagebox.showinfo("Greffier", "Saisis un nom.")
            return
        try:
            nommage(self.config).nommer(identifiant, voix, nom)
        except (RuntimeError, ValueError, OSError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        self.champ_nom.delete(0, "end")
        self._charger_voix()
        self.etat_bas.configure(text=f"{nom} est en banque.")
        self._dire("greffier", f"{nom} est en banque, et sera reconnue seule aux "
                               "prochaines réunions.")
        self._regenerer_apres_nommage(identifiant)

    def _regenerer_apres_nommage(self, identifiant: str) -> None:
        """Rejoue la rédaction, dans un fil séparé : le rédacteur peut appeler
        une API distante, et bloquerait la fenêtre le temps de répondre."""
        from greffier.application.restituer import regenerer_compte_rendu
        from greffier.composition import depot, redacteur

        chemin = self.config.chemins.comptes_rendus / f"{identifiant}.md"
        if not chemin.exists():
            return
        moteur = redacteur(self.config)
        if moteur is None:
            return

        def faire(dire: Callable[[str], None]) -> Any:
            dire("rédaction…")
            reunion = depot(self.config).lire(identifiant)
            return regenerer_compte_rendu(reunion, moteur)

        self._lancer(Travail(
            intitule="régénération", faire=faire,
            fini=lambda texte, souci: self._regeneration_finie(chemin, texte, souci),
        ))

    def _regeneration_finie(self, chemin: Path, texte: Any, souci: Exception | None) -> None:
        if souci is not None:
            self._dire("greffier", f"La régénération du compte rendu a échoué : {souci}")
            return
        chemin.write_text(texte, encoding="utf-8")
        self._dire("greffier", "Compte rendu régénéré avec les nouveaux noms.")

    def _ecouter(self) -> None:
        import shutil
        import subprocess

        from greffier.application.nommer import extraire_audio, voix_a_nommer

        identifiant, voix = self._selection(), self._voix_selectionnee()
        if not (identifiant and voix):
            messagebox.showinfo("Greffier", "Choisis une réunion, puis une voix.")
            return
        lecteur = shutil.which("afplay") or shutil.which("aplay") or shutil.which("ffplay")
        if lecteur is None:
            messagebox.showinfo("Greffier", "Aucun lecteur audio disponible.")
            return
        try:
            detail = self.depot.lire(identifiant)
            candidate = next(c for c in voix_a_nommer(detail) if c.voix == voix)
            if candidate.extrait is None:
                messagebox.showinfo("Greffier",
                                    "Aucun extrait exploitable pour cette voix.")
                return
            sortie = self.config.chemins.donnees / "extraits" / f"{identifiant}-{voix}.wav"
            extrait = extraire_audio(detail.audio, candidate.extrait, sortie)
        except (StopIteration, RuntimeError, OSError, ValueError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        arguments = ([lecteur, "-nodisp", "-autoexit", "-loglevel", "error", str(extrait)]
                     if lecteur.endswith("ffplay") else [lecteur, str(extrait)])
        subprocess.Popen(arguments)

    # ---------------------------------------------------------- conversation

    def _dire(self, qui: str, texte: str) -> None:
        self.fil.configure(state="normal")
        if qui in ("moi", "greffier"):
            self.fil.insert("end", "TOI\n" if qui == "moi" else "GREFFIER\n", "qui")
            self.fil.insert("end", f"{texte}\n", "dit")
        else:
            self.fil.insert("end", f"{texte}\n", "note")
        self.fil.see("end")
        self.fil.configure(state="disabled")

    def _demander(self) -> None:
        from greffier.composition import redacteur

        question = self.question.get().strip()
        if not question:
            return
        identifiant = self._selection()
        if identifiant is None:
            self._dire("note", "Choisis d'abord une réunion dans l'onglet Réunions.")
            return
        source = self.config.chemins.comptes_rendus / f"{identifiant}.md"
        if not source.exists():
            self._dire("note", f"« {identifiant} » n'a pas encore de compte rendu. "
                               "Onglet Réunions, « Traiter ».")
            return
        moteur = redacteur(self.config)
        if moteur is None:
            self._dire("note", "Aucun rédacteur configuré : « greffier configurer ».")
            return

        self.question.delete(0, "end")
        self._dire("moi", question)
        compte_rendu = source.read_text(encoding="utf-8")

        def faire(dire: Callable[[str], None]) -> Any:
            dire("réflexion…")
            return moteur.rediger(
                "Tu réponds à une question sur le compte rendu ci-dessous. Réponds "
                "brièvement, en français, en t'appuyant uniquement sur ce document. "
                "Si la réponse n'y est pas, dis-le plutôt que de la deviner. "
                "N'emploie ni tiret cadratin ni demi-cadratin.\n\n"
                f"Question : {question}\n\nCompte rendu :\n{compte_rendu}"
            )

        self._lancer(Travail(
            intitule="question",
            faire=faire,
            fini=lambda reponse, souci: self._dire(
                "note" if souci else "greffier", str(souci) if souci else str(reponse)
            ),
        ))

    # ------------------------------------------------------------------ boucle

    def tourner(self) -> None:
        self.racine.mainloop()


def ouvrir(config: Config) -> None:
    """Point d'entrée de la fenêtre."""
    Fenetre(config).tourner()
