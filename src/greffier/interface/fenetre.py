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

from greffier.adaptateurs.configuration import Config
from greffier.adaptateurs.niveaux_direct import Releve, relever
from greffier.application.suivre import (
    GENRE_CORRECTION,
    GENRE_ETAT,
    GENRE_REUNION,
    demander,
    demander_une_separation,
    fichiers,
    lire_depuis,
    rejouer,
)
from greffier.domaine.canaux import QuiParle
from greffier.domaine.compte_rendu import titre
from greffier.domaine.direct import Fil, TourDirect
from greffier.domaine.modeles import Phase
from greffier.emplacements import situer_tcl
from greffier.interface.apparence import (
    MAIN,
    BarreDeBoutons,
    Bouton,
    Defileur,
    Liste,
    Onglets,
    Vumetre,
)
from greffier.interface.lisible import etat_du_direct, horloge, sujet_lisible
from greffier.interface.style import degrade, palette, police, police_titre

PERIODE_MS = 250

PERIODE_MICROS_MS = 1000

PULSATION_MS = 50

PULSATION_S = 1.6

_LIBELLE = 84

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
        self._questions_vues: set[int] = set()
        self._questions_attente: list[Any] = []
        self._apprentissage_attente: Any = None
        self._conversation_affichee = ""
        self._apprentissage: Any = None
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
        # Après tous les onglets : l'annonce s'écrit dans la Conversation, qui
        # n'existe pas encore quand l'onglet Réunions se construit.
        self._signaler_les_reprises()
        self._signaler_un_paquet_plus_recent()

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
        self.titre.configure(font=police_titre(21))
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
        actions = BarreDeBoutons(dedans, self.couleurs)
        actions.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        for intitule, action, largeur in (
            ("Traiter", self._traiter_selection, 100),
            # Distinct de « Traiter », qui retranscrit tout : reprendre la seule
            # rédaction prend quelques secondes là où la chaîne complète prend
            # plusieurs minutes, et c'est le cas courant après un échec.
            ("Rédiger", self._rediger_selection, 100),
            ("Ouvrir", self._ouvrir_compte_rendu, 96),
            # « Envoyer par courriel » en entier. Le raccourcir à « Envoyer »
            # gagnait une place qu'on n'a plus besoin de gagner — quatre
            # colonnes de 187 px tiennent dans la largeur minimale — et créait
            # une vraie ambiguïté : dans un onglet « Réunions », « Envoyer »
            # sans complément peut se lire « envoyer quoi, à qui, comment ».
            # Un bouton doit dire ce qui se passe quand on le presse.
            ("Envoyer par courriel", self._envoyer_selection, 180),
            ("Déposer…", self._deposer_des_fichiers, 116),
            ("Renommer", self._renommer_selection, 110),
            ("Supprimer", self._oublier_selection, 110),
            ("Rafraîchir", self._charger_reunions, 116),
        ):
            actions.ajouter(
                Bouton(actions, intitule, action, self.couleurs,
                       largeur=largeur, hauteur=34),
                largeur,
            )
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
        self.direct_etat.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # Un seul réglage ici, et c'est la voix. L'assistant participe
        # toujours : il écoute, il prend des notes, il pose ses questions dans
        # la conversation, c'est son travail. Ce qui se décide, c'est s'il se
        # fait **entendre** dans la pièce, parce que cela dépend de la réunion
        # et de qui est là.
        #
        # Deux boutons dont l'un disait « Lucie participe » laissaient croire
        # qu'elle pouvait ne pas participer, et ne se distinguaient pas d'un
        # coup d'oeil.
        #
        # « Fournir un document » est ici et non seulement dans l'onglet
        # Conversation : un document se fournit **pendant** la réunion, donc
        # depuis l'onglet où l'on est pendant la réunion.
        barre = tk.Frame(dedans, bg=c.carte)
        barre.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.bouton_voix = Bouton(
            barre, self._intitule_voix(), self._basculer_la_voix, self.couleurs,
            largeur=230, hauteur=34,
            principal=self.config.assistant.voix != "aucun")
        self.bouton_voix.grid(row=0, column=0, sticky="w")
        # L'initiative est l'autre chose qui dépend de la réunion, et elle est
        # plus délicate que la voix : une intervention non sollicitée coupe
        # quelqu'un. Elle était donc livrée éteinte, sans moyen de l'allumer.
        self.bouton_initiative = Bouton(
            barre, self._intitule_initiative(), self._basculer_l_initiative,
            self.couleurs, largeur=250, hauteur=34,
            principal=self.config.assistant.initiative)
        self.bouton_initiative.grid(row=0, column=1, sticky="w", padx=(10, 0))
        Bouton(barre, "Fournir un document", self._fournir_un_document,
               self.couleurs, largeur=190, hauteur=34).grid(
                   row=0, column=2, sticky="w", padx=(10, 0))
        # Sur sa propre ligne, et non à côté des boutons : à côté, la place
        # restante dépend de la largeur de la fenêtre, et le texte se faisait
        # couper au milieu d'un mot, constaté à la capture.
        self.mot_participation = self._texte(
            dedans, "", taille=11, pale=True, wraplength=740, justify="left")
        self.mot_participation.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._dire_la_participation()

        cadre = tk.Frame(dedans, bg=c.carte)
        cadre.grid(row=3, column=0, sticky="nsew")
        cadre.columnconfigure(0, weight=1)
        cadre.rowconfigure(0, weight=1)
        dedans.rowconfigure(3, weight=1)

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

    def _intitule_voix(self) -> str:
        nom = self.config.assistant.nom
        return (f"Couper la voix de {nom}"
                if self.config.assistant.voix != "aucun"
                else f"Donner la voix à {nom}")

    def _basculer_la_voix(self) -> None:
        """Lui donne la parole, ou la lui retire, sans la faire taire.

        Distinct du bouton de participation : sans voix, elle pose toujours ses
        questions, mais dans la conversation, et on lui répond au clavier. Avec,
        elle se fait entendre dans la pièce. Deux réunions différentes.
        """
        from greffier.adaptateurs import configuration as reglages
        from greffier.adaptateurs.voix_neuronale import VoixNeuronale, faire_taire

        avant = self.config.assistant.voix
        if avant != "aucun":
            # Coupé ici, tout de suite, et non par le réglage : la veille est un
            # autre processus et ne le relit qu'à la tranche suivante, soit
            # jusqu'à quinze secondes plus tard. Mesuré en réunion — on appuie,
            # elle continue de parler, et le bouton paraît cassé.
            faire_taire(self.config.chemins.baillon)
            self.config.assistant.voix = "aucun"
        else:
            # La meilleure voix disponible, sans demander : la neuronale si son
            # modèle est là, celle du système sinon.
            self.config.assistant.voix = (
                "kokoro"
                if VoixNeuronale(self.config.chemins.voix_de_synthese).installee
                else "systeme"
            )
        try:
            reglages.sauver(self.config)
        except OSError as souci:
            self.config.assistant.voix = avant
            messagebox.showerror("Greffier", f"Réglage non enregistré : {souci}")
            return
        self.bouton_voix.intituler(self._intitule_voix())
        self.bouton_voix.mettre_en_avant(self.config.assistant.voix != "aucun")
        self._dire_la_participation()
        if hasattr(self, "reglage_voix_assistant"):
            self.reglage_voix_assistant.choisir(self.config.assistant.voix)

    def _intitule_initiative(self) -> str:
        nom = self.config.assistant.nom
        return (f"{nom} n'intervient que si on l'appelle"
                if self.config.assistant.initiative
                else f"Laisser {nom} intervenir d'elle-même")

    def _basculer_l_initiative(self) -> None:
        """Lui permet de parler sans qu'on l'ait appelée, ou le lui retire.

        Éteinte, elle ne dit un mot que si son nom est prononcé — c'est la règle
        qui la rend supportable en réunion. Allumée, elle peut signaler une
        décision sans responsable, une question restée en l'air, un écart avec
        un document fourni. Jamais plus d'une fois par « repos », et jamais dans
        une phrase de quelqu'un : la politesse est dans `participation`.
        """
        from greffier.adaptateurs import configuration as reglages

        avant = self.config.assistant.initiative
        self.config.assistant.initiative = not avant
        try:
            reglages.sauver(self.config)
        except OSError as souci:
            self.config.assistant.initiative = avant
            messagebox.showerror("Greffier", f"Réglage non enregistré : {souci}")
            return
        self.bouton_initiative.intituler(self._intitule_initiative())
        self.bouton_initiative.mettre_en_avant(self.config.assistant.initiative)
        self._dire_la_participation()

    def _dire_la_participation(self) -> None:
        """Ce que le bouton vient de changer, en clair.

        Un bouton qui bascule sans rien dire laisse deviner dans quel état on
        est, et ici l'état s'entend dans la pièce : autant l'écrire.
        """
        nom = self.config.assistant.nom
        if self.config.assistant.voix == "aucun":
            mot = (f"{nom} suit la réunion et pose ses questions dans l'onglet "
                   "Conversation : répondez-lui au clavier.")
        else:
            mot = (f"{nom} peut prendre la parole. Appelez-la par son nom pour "
                   "lui poser une question.")
        mot += (" Elle peut aussi intervenir d'elle-même."
                if self.config.assistant.initiative
                else " Elle n'intervient jamais sans qu'on l'appelle.")
        self.mot_participation.configure(text=mot)

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
        self._suivre_les_questions()

    def _suivre_les_questions(self) -> None:
        """Affiche ce que l'outil demande, et pose le compte sur l'onglet.

        Rien ne surgit : une boîte de dialogue au milieu d'une réunion coûte
        plus qu'elle n'apporte. La pastille signale qu'il y a quelque chose à
        voir, on y va quand on veut.
        """
        from greffier.adaptateurs import questions_fichier

        if not self._fil_reunion:
            return
        fichier = questions_fichier.fichier_des_questions(
            self.config.chemins.questions, self._fil_reunion
        )
        attente, _ = questions_fichier.lire(fichier)
        for en_attente in attente:
            if en_attente.numero in self._questions_vues:
                continue
            self._questions_vues.add(en_attente.numero)
            self._dire("note", f"❓ {en_attente.question.texte}")
            self._dire("note", "   Réponds « oui » ou « non » ci-dessous, ou "
                               "écris l'orthographe juste.")
        self._questions_attente = attente
        self.onglets.marquer("Conversation", len(attente))

    def _oublier_le_direct(self, identifiant: str) -> None:
        """Repart de zéro : une autre réunion, un autre fil."""
        self._fil = Fil()
        self._fil_reunion = identifiant
        self._fil_position = 0
        self._fil_annonce = ""
        self._questions_vues = set()
        self._questions_attente = []
        self.onglets.marquer("Conversation", 0)
        # Une autre réunion, une autre conversation : celle qui est à l'écran
        # n'est plus la bonne.
        self._conversation_affichee = ""
        self._charger_la_conversation()
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
            repere, "<Enter>", lambda _e: self.fil_texte.configure(cursor=MAIN)
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
            # Pourquoi ce nom est proposé, à l'endroit où l'on décide de le
            # garder ou non. « Sophie ? » ne dit pas s'il s'agit d'une quasi
            # certitude ou d'une hypothèse fragile, et c'est exactement ce
            # qu'il faut savoir avant de corriger — surtout dans le cas le plus
            # trompeur, où le nom est peut-être celui du voisin.
            if voix.confiance:
                menu.add_command(label=f"   {voix.confiance}", state="disabled")
                menu.add_separator()
            self._garnir(menu, noms, numero, toute_la_voix=True)
            menu.add_separator()
            phrase = tk.Menu(menu, tearoff=0, font=police(12))
            self._garnir(phrase, noms, numero, toute_la_voix=False)
            menu.add_cascade(label="Seulement cette phrase…", menu=phrase)
            # Le retour arrière qui manquait. Réunir deux voix se faisait d'un
            # clic, se défaisait par rien : deux personnes réunies à tort le
            # restaient jusqu'au compte rendu.
            if self._fil.peut_separer(tour.voix):
                menu.add_separator()
                menu.add_command(
                    label="Ce n'est pas la même personne : séparer les deux voix",
                    command=functools.partial(self._separer_le_direct, tour.voix),
                )
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

    def _separer_le_direct(self, identifiant: str) -> None:
        """Défait la dernière réunion qui a produit cette voix.

        Ici d'abord, comme la correction : un clic doit se voir tout de suite.
        Le processus d'écoute rend ensuite chaque empreinte à sa voix — lui seul
        les tient, et c'est de ça que dépend ce qui entrera en banque.
        """
        defaite = self._fil.separer(identifiant)
        if defaite is None:
            messagebox.showinfo(
                "Greffier", "Cette voix n'a absorbé aucune autre voix."
            )
            return
        _, demandes = fichiers(self.config.chemins.direct, self._fil_reunion)
        try:
            demander_une_separation(demandes, identifiant)
        except OSError as souci:
            messagebox.showerror(
                "Greffier",
                f"La séparation est affichée mais n'a pas pu être transmise : {souci}",
            )
        self._repeindre_le_direct()
        rendue = self._fil.etiquette(defaite.source)
        self.etat_bas.configure(
            text=f"Les deux voix sont séparées. « {rendue} » attend un nom."
        )

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
        # Se tromper de nom était sans retour : on ne pouvait que renommer
        # par-dessus, ce qui ajoutait une empreinte fausse à la banque au lieu
        # d'en retirer une.
        Bouton(saisie, "Retirer le nom", self._oublier_le_nom, self.couleurs,
               largeur=150, hauteur=34).pack(side="left", padx=(9, 0))

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
        # Ici et pas dans « Réunions » : un document se fournit pendant qu'on
        # en parle, et c'est la conversation qui répondra dessus.
        Bouton(saisie, "Fournir un document", self._fournir_un_document,
               self.couleurs, largeur=176, hauteur=36).grid(
                   row=0, column=2, padx=(8, 0))
        # L'accueil est peint et non « dit » : le garder reviendrait à écrire une
        # ligne d'invite dans le journal de chaque réunion.
        self._peindre_le_tour(
            "note",
            "Pose une question sur la réunion en cours, ou sur celle choisie dans "
            "l'onglet Réunions. Pendant une réunion, la réponse vient du fil du "
            "direct, et je peux chercher en ligne si la question sort de la réunion.",
        )
        self._peindre_le_tour(
            "note",
            "Tu peux aussi m'apprendre quelque chose en une phrase — « retiens "
            "que FAST veut dire formulaire d'attestation » — ou me fournir un "
            "document : je réponds dessus et j'en propose le vocabulaire.",
        )

    # ---------------------------------------------------------------- réglages

    MODELES_TRANSCRIPTION = (
        ("large-v3-turbo", "large-v3-turbo — le plus juste, conseillé"),
        ("large-v3", "large-v3 — plus lent, sans gain mesuré ici"),
        ("small", "small — rapide, pour les postes modestes"),
    )
    THEMES = (("systeme", "Selon le système"), ("clair", "Clair"), ("sombre", "Sombre"))
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
        # Deux boutons de même largeur, comme la barre de l'onglet Réunions :
        # dans une même fenêtre, deux barres d'actions qui ne se ressemblent pas
        # se remarquent.
        self.bouton_session = Bouton(boutons, "Se connecter", self._session_claude,
                                     self.couleurs, largeur=228, hauteur=32)
        self.bouton_session.pack(side="left", padx=(0, 9))
        # « Mettre à jour Claude Code » et non « Mettre à jour » : sous un bloc
        # intitulé « Compte Claude », le libellé court se lit « mettre à jour le
        # compte », ce qui n'est pas du tout ce qu'il fait. Un bouton doit dire
        # ce qui se passe quand on le presse.
        self.bouton_maj = Bouton(boutons, "Mettre à jour Claude Code",
                                 self._mettre_a_jour_claude,
                                 self.couleurs, largeur=228, hauteur=32)
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

        rang = self._bloc(
            dedans, rang, "Assistant",
            "Le prénom auquel il répond pendant la réunion, et sa voix. "
            "Sa participation s'allume dans l'onglet En direct.")
        # Une liste et non une saisie : un prénom tapé au hasard n'est pas
        # forcément rendu par le modèle de transcription, et rien ne le dirait à
        # celui qui l'a tapé — il appellerait dans le vide. Ceux-ci ont été
        # éprouvés, et chacun porte sa voix.
        self.reglage_nom_assistant = self._liste_deroulante(
            dedans, rang, "Prénom", largeur=392)
        rang += 1
        self.reglage_voix_assistant = self._liste_deroulante(
            dedans, rang, "Voix", largeur=392)
        rang += 1

        rang = self._bloc(dedans, rang, "Apparence", "")
        self.reglage_theme = self._liste_deroulante(dedans, rang, "Thème")
        rang += 1

        rang = self._bloc(dedans, rang, "Version",
                          "Greffier lui-même, et ce qui est publié.")
        self.etat_version = tk.Label(
            dedans, text="", bg=self.couleurs.carte, fg=self.couleurs.encre_pale,
            font=police(11), anchor="w", justify="left",
        )
        self.etat_version.grid(row=rang, column=0, columnspan=2, sticky="w",
                               pady=(0, 6))
        rang += 1
        boutons_version = tk.Frame(dedans, bg=self.couleurs.carte)
        boutons_version.grid(row=rang, column=0, columnspan=2, sticky="w",
                             pady=(0, 2))
        # « Chercher une mise à jour » et non un libellé plus court : c'est le
        # seul bouton de sa ligne, donc il n'impose sa largeur à personne, et
        # l'action mérite d'être dite en entier — elle interroge le réseau.
        self.bouton_maj_greffier = Bouton(
            boutons_version, "Chercher une mise à jour",
            self._chercher_une_mise_a_jour, self.couleurs, largeur=210, hauteur=32,
        )
        self.bouton_maj_greffier.pack(side="left", padx=(0, 9))
        rang += 1

        self._brancher_les_reglages()
        # Relire à l'affichage plutôt que d'offrir un bouton : la session peut
        # avoir été ouverte dans le terminal entre-temps, et l'événement <Map>
        # est justement émis quand la page revient au premier plan.
        page.bind("<Map>", lambda _e: self._dire_le_compte())
        # Et au retour du navigateur : se connecter ouvre un terminal puis une
        # page web, et l'on revient à Greffier **sans changer d'onglet** — aucun
        # « Map » n'est alors émis, donc rien ne se relisait alors que le message
        # promettait le contraire.
        self.racine.bind("<FocusIn>", self._au_retour, add="+")
        # Les enfants interceptent la molette avant leur parent : sans cette
        # passe, la roue ne fait rien dès que le curseur est sur une étiquette.
        self._ecouter_la_molette(dedans)
        self._garnir_les_reglages()
        self._dire_le_compte()
        self._dire_la_version()

    def _au_retour(self, _evenement: object = None) -> None:
        """Relit ce qui a pu changer pendant qu'on était ailleurs.

        Le compte se lit dans un fichier, sans appel réseau : le relire à chaque
        retour de focus ne coûte rien, et c'est le seul moment où l'on peut
        attraper une session ouverte dans un terminal.
        """
        if self.onglets.courant == "Réglages":
            with contextlib.suppress(Exception):
                self._dire_le_compte()

    def _dire_la_version(self) -> None:
        """Affiche la version installée, sans rien demander au réseau.

        Sans ce repère, personne ne pouvait dire quelle version tournait : le
        numéro n'existait que dans le paquet macOS, et l'application, elle, ne
        le lisait pas.
        """
        from greffier.adaptateurs.mises_a_jour import version_installee

        installee = version_installee()
        self.etat_version.configure(
            text=f"Version {installee}." if installee
            else "Version inconnue : paquet installé sans métadonnées."
        )

    def _chercher_une_mise_a_jour(self) -> None:
        """Demande à GitHub s'il existe mieux. N'installe rien.

        Remplacer l'application pendant qu'elle tourne est un problème distinct :
        le faire en effet de bord d'une vérification serait le pire moment.
        """
        from greffier.adaptateurs.mises_a_jour import verifier

        self.bouton_maj_greffier.activer(False)
        self.etat_version.configure(text="Vérification…")

        def fini(verdict: Any, souci: Exception | None) -> None:
            self.bouton_maj_greffier.activer(True)
            if souci is not None:
                self.etat_version.configure(text=f"Vérification impossible : {souci}")
                return
            self.etat_version.configure(text=verdict.dire())
            if not verdict.mise_a_jour:
                return
            self._proposer_l_installation(verdict)

        self._lancer(Travail(
            intitule="mise à jour",
            faire=lambda _dire: verifier(),
            fini=fini,
        ))

    def _proposer_l_installation(self, verdict: Any) -> None:
        """Propose d'installer, par la voie qui existe sur ce poste.

        Deux voies, et la seconde est celle de presque tout le monde : depuis le
        dépôt quand il est là — c'est le poste de qui développe — et sinon
        depuis le **binaire publié pour ce système**. Auparavant il n'y avait
        que la première, donc le bouton ne servait à personne d'autre qu'à moi.
        """
        from greffier.adaptateurs.mises_a_jour import installable

        depuis_le_depot, raison = installable()
        if depuis_le_depot:
            self._installer_depuis_le_depot(verdict)
        elif verdict.telechargeable:
            self._installer_depuis_le_binaire(verdict)
        else:
            self._peindre_le_tour("greffier", (
                f"{verdict.dire()} Rien à installer d'ici : {raison}, et la "
                "version publiée ne porte pas d'archive pour ce système."
                + (f" À voir : {verdict.adresse}" if verdict.adresse else "")
            ))

    RIEN_N_EST_PERDU = (
        "Les réunions, les comptes rendus, la banque de voix, les "
        "conversations et les réglages ne sont pas touchés : ils vivent hors "
        "de l'application."
    )

    def _installer_depuis_le_depot(self, verdict: Any) -> None:
        from greffier.adaptateurs.mises_a_jour import installer

        if not messagebox.askyesno(
            "Greffier",
            f"{verdict.dire()}\n\nInstaller maintenant ? Greffier va se fermer, "
            f"se reconstruire depuis son dépôt, puis se relancer.\n\n"
            f"{self.RIEN_N_EST_PERDU}",
        ):
            return
        lance, ou = installer()
        if not lance:
            messagebox.showerror("Greffier", f"Mise à jour impossible : {ou}")
            return
        self._se_fermer_pour_la_mise_a_jour()

    def _installer_depuis_le_binaire(self, verdict: Any) -> None:
        """Télécharge l'archive publiée pour ce système, puis remplace le paquet.

        Le téléchargement se fait dans un fil : cent cinquante mégaoctets
        figeraient la fenêtre une minute ou deux, et une fenêtre figée sans
        rien dire passe pour cassée.
        """
        import platform

        from greffier.adaptateurs.mises_a_jour import (
            installer_depuis_la_publication,
        )

        if not messagebox.askyesno(
            "Greffier",
            f"{verdict.dire()}\n\nTélécharger « {verdict.artefact_nom} » et "
            "l'installer ? Greffier va se fermer puis se relancer sur la "
            "nouvelle version.\n\n"
            f"{self.RIEN_N_EST_PERDU}",
        ):
            return

        sur_mac = platform.system() == "Darwin"

        def faire(dire: Callable[[str], None]) -> Any:
            def avancement(recu: int, total: int) -> None:
                if total:
                    dire(f"téléchargement… {recu * 100 // total} %")
                else:
                    dire(f"téléchargement… {recu // 1024 // 1024} Mo")

            return installer_depuis_la_publication(
                verdict, sys.executable, avancement=avancement
            )

        def fini(resultat: Any, souci: Exception | None) -> None:
            if souci is not None:
                messagebox.showerror("Greffier", f"Mise à jour impossible : {souci}")
                return
            lance, ou = resultat
            if not lance:
                messagebox.showerror("Greffier", f"Mise à jour impossible : {ou}")
                return
            if not sur_mac:
                # Dire où elle est plutôt que de prétendre l'installer :
                # remplacer un exécutable Windows qui tourne demande autre
                # chose, et une fausse promesse coûterait plus qu'un chemin.
                self._peindre_le_tour("greffier", (
                    f"La version {verdict.disponible} est téléchargée dans "
                    f"{ou}. Ferme Greffier, remplace le dossier de "
                    f"l'application par celui-là, et relance. {self.RIEN_N_EST_PERDU}"
                ))
                return
            self._se_fermer_pour_la_mise_a_jour()

        self._lancer(Travail(intitule="mise à jour", faire=faire, fini=fini))

    def _se_fermer_pour_la_mise_a_jour(self) -> None:
        """Le relais attend la fin de ce processus avant de toucher au paquet :
        se fermer fait partie de la mise à jour."""
        self.etat_version.configure(text="Mise à jour en cours, fermeture…")
        self.racine.after(400, self.racine.destroy)

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

    def _prenoms_reglables(self) -> list[tuple[str, str]]:
        """Les prénoms éprouvés, chacun avec le genre de sa voix.

        Le genre est dit parce qu'il est imposé par le prénom : on choisit
        « Martin » et on obtient une voix masculine, sans réglage de plus à
        accorder.
        """
        from greffier.adaptateurs.configuration import GENRES, PRENOMS

        choix = [(prenom, f"{prenom} — {GENRES[locuteur]}")
                 for prenom, locuteur in PRENOMS.items()]
        # Un prénom réglé à la main hors de la liste reste choisi : le fichier
        # de configuration l'autorise, la fenêtre n'a pas à l'effacer.
        actuel = self.config.assistant.nom
        if actuel and actuel not in PRENOMS:
            choix.insert(0, (actuel, f"{actuel} — réglé à la main"))
        return choix

    def _voix_reglables(self) -> list[tuple[str, str]]:
        """Les voix proposées, en disant laquelle est installée.

        Proposer la voix neuronale sans dire qu'elle manque enverrait chercher
        un défaut là où il n'y a qu'un modèle à télécharger.
        """
        from greffier.adaptateurs.voix_neuronale import VoixNeuronale

        installee = VoixNeuronale(self.config.chemins.voix_de_synthese).installee
        return [
            ("kokoro", "Voix naturelle" if installee
             else "Voix naturelle (modèle absent, repli sur le système)"),
            ("systeme", "Voix du système"),
            ("aucun", "Aucune, il répond par écrit"),
        ]

    def _garnir_les_reglages(self) -> None:
        """Remplit le formulaire depuis la configuration en vigueur."""
        from greffier.adaptateurs.configuration import MODELES_CLAUDE

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
        self.reglage_nom_assistant.garnir(self._prenoms_reglables(),
                                          self.config.assistant.nom)
        self.reglage_voix_assistant.garnir(self._voix_reglables(),
                                           self.config.assistant.voix)
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
            from greffier.adaptateurs.redaction_ollama import modeles_disponibles

            presents = modeles_disponibles()
            choix = tuple((m, m) for m in presents) or (("qwen3:8b", "qwen3:8b — à télécharger"),)
        else:
            choix = (("", "Sans objet : aucun rédacteur"),)
        self.reglage_modele_redaction.garnir(
            list(choix), self.config.compte_rendu.modele or (choix[0][0] if choix else ""))
        self.reglage_modele_redaction.activer(moteur != "aucun")

    def _dire_le_compte(self) -> None:
        """Affiche l'état du compte, et accorde les boutons à cet état."""
        from greffier.adaptateurs import diagnostic_systeme as diagnostic

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

        from greffier.adaptateurs import diagnostic_systeme as diagnostic

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
        # Le retour de focus suffit dans le cas courant, mais la connexion se
        # termine parfois pendant qu'on regarde le navigateur, Greffier n'ayant
        # jamais reperdu le focus. On surveille donc quelques minutes.
        self._guetter_la_session(tours=60)

    def _guetter_la_session(self, tours: int) -> None:
        """Relit le compte toutes les trois secondes, le temps qu'il change."""
        from greffier.adaptateurs import diagnostic_systeme as diagnostic

        def signature() -> tuple[str, str, str] | None:
            """De quoi voir qu'on a changé de compte, sans lire aucun jeton."""
            compte = diagnostic.compte_claude()
            if compte is None:
                return None
            return (compte.adresse, compte.organisation, compte.formule)

        avant = signature()

        def regarder(restants: int) -> None:
            if restants <= 0:
                return
            if signature() != avant:
                self._dire_le_compte()
                return
            self.racine.after(3000, lambda: regarder(restants - 1))

        self.racine.after(3000, lambda: regarder(tours))

    def _mettre_a_jour_claude(self) -> None:
        """Lance « claude update », dans un fil : il télécharge."""
        from greffier.adaptateurs import diagnostic_systeme as diagnostic

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
        from greffier.adaptateurs import configuration as reglages

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
        # Le prénom pose sa voix du même geste : les choisir séparément
        # permettrait « Martin » avec une voix féminine, ce que personne ne veut.
        from greffier.adaptateurs.configuration import PRENOMS

        neuf.assistant.nom = (self.reglage_nom_assistant.valeur()
                              or self.config.assistant.nom)
        neuf.assistant.locuteur = PRENOMS.get(neuf.assistant.nom,
                                              self.config.assistant.locuteur)
        neuf.assistant.voix = self.reglage_voix_assistant.valeur()
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
            self.pastille.itemconfigure(self._point, fill=degrade(c.actif, c.carte, part * 0.65))
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
            return
        self._eprouver_l_envoi()

    def _eprouver_l_envoi(self) -> None:
        """Vérifie maintenant que le compte rendu pourra partir.

        Maintenant et non à la fin, et c'est tout l'objet : le 2026-09-10,
        l'envoi d'une réunion de 1 h 42 a échoué à 12 h 17 devant un écran
        verrouillé, deux heures après le moment où quelqu'un était au clavier
        et où un clic suffisait. Une sonde sans effet, dite dans la
        conversation et non en fenêtre : c'est une information sur le poste,
        pas une raison d'interrompre le démarrage d'une réunion.
        """
        from greffier.composition import _expediteur

        if not self.config.compte_rendu.destinataire:
            return
        with contextlib.suppress(Exception):
            expediteur = _expediteur(self.config)
            # Tous les moyens d'envoi n'ont pas de sonde : écrire dans un
            # fichier ne peut pas échouer pour une autorisation.
            sonde = getattr(expediteur, "eprouver", None)
            empeche = sonde() if callable(sonde) else None
            if empeche:
                self._dire("note", f"Avant la fin de la réunion : {empeche}")

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
            faire=self._chaine(audio, etat.evenements, etat.debut, etat.terminee_le),
            fini=lambda resultat, souci: self._traitement_fini(audio, resultat, souci),
        ))

    def _chaine(
        self,
        audio: Path,
        evenements: list[str] | None = None,
        commencee_le: datetime | None = None,
        terminee_le: datetime | None = None,
    ) -> Callable[[Callable[[str], None]], Any]:
        """Prépare l'exécution de la chaîne, l'avancement remonté à l'écran."""

        def faire(dire: Callable[[str], None]) -> Any:
            from greffier.composition import assembler, enregistrement

            chaine = assembler(self.config)
            # Voir cli.traiter : le journal est propre à cette réunion.
            chaine.journal = enregistrement(self.config).pour(audio.stem)
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
                commencee_le=commencee_le,
                terminee_le=terminee_le,
            )

        return faire

    def _traitement_fini(self, audio: Path, resultat: Any, souci: Exception | None) -> None:
        self._charger_reunions()
        if souci is not None:
            self._echec_de_traitement(audio, souci)
            return
        for avertissement in getattr(resultat, "avertissements", []):
            self._dire("note", avertissement)
        self.etat_bas.configure(text="Compte rendu prêt.")
        self._choisir(audio.stem)
        self.onglets.montrer("Conversation")
        self._proposer_la_suite(audio.stem, resultat)
        self._sauvegarder_sans_bruit()

    def _sauvegarder_sans_bruit(self) -> None:
        """Copie les données après une réunion traitée, sans rien demander.

        Le moment est le bon : le travail vient d'être produit, et personne n'y
        pense après. Sans bruit parce qu'une sauvegarde réussie n'a rien à dire
        — seul un échec mérite un mot, et il ne doit pas non plus interrompre.
        """
        if not self.config.sauvegarde.apres_chaque_reunion:
            return
        from greffier.application import sauvegarder
        from greffier.emplacements import dossier_config

        destination = (
            Path(self.config.sauvegarde.dossier).expanduser()
            if self.config.sauvegarde.dossier else self.config.chemins.sauvegardes
        )
        try:
            faite = sauvegarder.faire(
                self.config.chemins.donnees, dossier_config(), destination,
                gardees=self.config.sauvegarde.gardees,
            )
        except (OSError, ValueError) as souci:
            self._dire("note", f"Sauvegarde impossible : {souci}")
            return
        if faite.sur_le_meme_disque:
            # Dit une fois, dans la conversation, plutôt qu'en fenêtre : c'est
            # une information, pas une alerte, mais elle ne doit pas se perdre.
            self._dire("note", (
                f"Données sauvegardées ({faite.octets / 1024**2:.1f} Mo), mais sur "
                "le même disque : règle « sauvegarde.dossier » vers un disque "
                "externe ou un espace synchronisé pour être vraiment à l'abri."
            ))

    def _echec_de_traitement(self, audio: Path, souci: Exception) -> None:
        """Dit ce qui reste, et propose de reprendre là où ça s'est arrêté.

        « Command timed out after 900 seconds » n'indiquait aucune action, alors
        que la transcription était sauvée et qu'un clic suffisait — constaté le
        2026-09-09, où la réponse « le compte rendu n'est pas arrivé » a coûté
        une demi-heure de recherche. Une alerte qui ne dit pas quoi faire fait
        croire que tout est perdu.
        """
        self.etat_bas.configure(text=f"Échec : {souci}")
        # Publiée et écrite **avant** toute boîte de dialogue, et c'est tout le
        # correctif : l'échec n'était rapporté que par une fenêtre modale et la
        # note n'était écrite qu'après le clic. Écran verrouillé, personne pour
        # cliquer, et l'état restait figé sur la phase en cours — « envoi » pour
        # une réunion de 1 h 42, le 2026-09-10. Tout ce qui relit cet état croit
        # alors qu'une réunion se traite encore : la veille, la ligne de
        # commande, et la reconstruction de l'application, qui refuse de se
        # relancer pendant une réunion.
        self._publier_l_echec(audio.stem, souci)
        self._dire("note", f"La rédaction de « {audio.stem} » a échoué : {souci} "
                           "La transcription est gardée, « Rédiger » la reprend.")
        transcrite = False
        with contextlib.suppress(OSError, ValueError):
            transcrite = bool(self.depot.lire(audio.stem).repliques)
        if not transcrite:
            messagebox.showerror("Greffier", str(souci))
            return
        if messagebox.askyesno(
            "Greffier",
            f"{souci}\n\nLa transcription et les voix sont gardées : rien n'est "
            "perdu. Seule la rédaction a échoué.\n\nReprendre la rédaction "
            "maintenant ?",
        ):
            self._rediger_seulement(audio.stem)

    def _publier_l_echec(self, identifiant: str, souci: Exception) -> None:
        """Écrit l'échec dans l'état de la réunion, pour les autres processus.

        Sans rien lever : on est déjà dans le traitement d'une erreur, et une
        seconde erreur ici ferait perdre le message de la première.
        """
        from greffier.composition import enregistrement

        with contextlib.suppress(Exception):
            journal = enregistrement(self.config).pour(identifiant)
            if journal is not None:
                journal.publier(Phase.ECHEC.value, f"Échec : {souci}")

    def _rediger_seulement(self, identifiant: str) -> None:
        """Rejoue la seule rédaction, sans réécouter ni retranscrire."""
        from greffier.application.restituer import regenerer_compte_rendu
        from greffier.composition import redacteur

        moteur = redacteur(self.config)
        if moteur is None:
            messagebox.showinfo("Greffier", "Aucun rédacteur configuré.")
            return

        def faire(dire: Callable[[str], None]) -> Any:
            dire("rédaction…")
            gardee = self.depot.lire(identifiant)
            texte = regenerer_compte_rendu(
                gardee, moteur, self.config.conversation.information
            )
            cible = self.config.chemins.comptes_rendus / f"{identifiant}.md"
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text(texte, encoding="utf-8")
            return texte

        def fini(_resultat: Any, souci: Exception | None) -> None:
            self._charger_reunions()
            if souci is not None:
                self.etat_bas.configure(text=f"Rédaction : {souci}")
                self._dire("note", f"La rédaction a encore échoué : {souci}")
                return
            self.etat_bas.configure(text="Compte rendu prêt.")
            self._dire("greffier", f"Le compte rendu de « {identifiant} » est prêt.")

        self._lancer(Travail(intitule=f"rédaction de {identifiant}",
                             faire=faire, fini=fini))

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
                sujet_lisible(identifiant, compte_rendu, detail.sujet),
                len(voix_a_nommer(detail)),
                sum(len(r.texte.split()) for r in detail.repliques),
                "oui" if compte_rendu.exists() else "non",
            ))
        if garde:
            self._choisir(garde)

    def _charger_la_conversation(self) -> None:
        """Réaffiche ce qui a déjà été dit sur la réunion choisie.

        Relu du disque plutôt que gardé en mémoire : c'est ce qui fait qu'une
        conversation survit à une fermeture de la fenêtre, à une mise à jour, et
        à un plantage.
        """
        from greffier.adaptateurs import conversations_fichier

        identifiant = self._fil_reunion or self._selection()
        if not identifiant or identifiant == self._conversation_affichee:
            return
        self._conversation_affichee = identifiant
        tours = conversations_fichier.lire(
            conversations_fichier.fichier_de(self.config.chemins.conversations,
                                             identifiant)
        )
        self._vider(self.fil)
        if not tours:
            self._peindre_le_tour(
                "note",
                "Pose une question sur la réunion en cours, ou sur celle choisie "
                "dans l'onglet Réunions. Pendant une réunion, la réponse vient du "
                "fil du direct, et je peux chercher en ligne si la question sort "
                "de la réunion.",
            )
            return
        self._peindre_le_tour("note", f"— conversation de « {identifiant} » —")
        for tour in tours:
            self._peindre_le_tour(tour.qui, tour.texte)

    def _charger_voix(self) -> None:
        from greffier.application.nommer import voix_a_nommer

        self._charger_la_conversation()
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

    def _rediger_selection(self) -> None:
        """Rejoue la rédaction de la réunion choisie, sans la retranscrire."""
        identifiant = self._selection()
        if identifiant is None:
            self.etat_bas.configure(text="Choisis une réunion dans la liste.")
            return
        self._rediger_seulement(identifiant)

    def _deposer_des_fichiers(self) -> None:
        """Choisit des fichiers, montre ce qu'il en ferait, puis demande.

        Le classement s'affiche avant d'agir : une vidéo de deux heures mal
        classée coûte une transcription pour rien, et un document classé en
        réunion produirait le compte rendu d'un texte que personne n'a
        prononcé.
        """
        from tkinter import filedialog

        from greffier.application import deposer as travail
        from greffier.domaine.depot import proposer, resumer

        choisis = filedialog.askopenfilenames(
            parent=self.racine,
            title="Déposer des enregistrements, des vidéos ou des documents",
        )
        if not choisis:
            return
        outils = travail.outils_presents()
        propositions = [
            proposer(Path(chemin), Path(chemin).stat().st_size, outils)
            for chemin in choisis
        ]
        detail = "\n".join(
            f"  {p.destin:9} {p.fichier.name}"
            + (f"\n             ⚠ {p.bloque_par}" if p.bloque_par else "")
            for p in propositions
        )
        if not messagebox.askyesno(
            "Greffier",
            f"{resumer(propositions)}\n\n{detail}\n\n"
            "Les sons et les vidéos deviennent des réunions à transcrire ; les "
            "documents servent à enrichir le contexte. Continuer ?",
        ):
            return

        redacteur_document = self._redacteur_de_documents(propositions)

        def faire(dire: Callable[[str], None]) -> list:  # type: ignore[type-arg]
            faits = []
            for numero, proposition in enumerate(propositions, start=1):
                dire(f"{proposition.fichier.name} ({numero}/{len(propositions)})…")
                faits.append(travail.executer(
                    proposition, self.config.chemins.enregistrements,
                    redacteur_document,
                ))
            return faits

        def fini(faits: Any, souci: Exception | None) -> None:
            self._charger_reunions()
            if souci is not None:
                self._dire("note", f"Dépôt interrompu : {souci}")
                return
            self._rendre_compte_du_depot(faits or [])

        self._lancer(Travail(intitule="dépôt", faire=faire, fini=fini))

    def _redacteur_de_documents(self, propositions: list) -> Any:  # type: ignore[type-arg]
        """Le rédacteur chargé de lire les documents, s'il y en a."""
        from greffier.composition import cartographe
        from greffier.domaine.depot import Destin

        if not any(p.destin is Destin.CONTEXTE and p.faisable for p in propositions):
            return None
        from greffier.adaptateurs.redaction_claude import RedacteurClaude
        from greffier.application.deposer import CONSIGNES_DOCUMENT

        moteur = cartographe(self.config)
        if isinstance(moteur, RedacteurClaude):
            moteur.consignes_propres = CONSIGNES_DOCUMENT
        return moteur

    def _rendre_compte_du_depot(self, faits: list) -> None:  # type: ignore[type-arg]
        """Dit ce que le dépôt a produit, et propose ce qu'il a appris."""
        a_transcrire: list[str] = []
        appris: list[tuple[str, str, str]] = []
        for fait in faits:
            if fait.souci:
                self._dire("note",
                           f"{fait.proposition.fichier.name} : {fait.souci}")
                continue
            if fait.produit is not None:
                a_transcrire.append(fait.produit.stem)
            appris.extend(fait.appris)

        if a_transcrire:
            self._dire("greffier", (
                f"{len(a_transcrire)} enregistrement(s) prêt(s) : "
                f"{', '.join(a_transcrire[:3])}"
                + ("…" if len(a_transcrire) > 3 else "")
                + ". Onglet Réunions, « Traiter »."
            ))
        self._proposer_au_contexte(appris)

    def _proposer_au_contexte(self, appris: list) -> None:  # type: ignore[type-arg]
        """Montre ce qu'un document a appris, et l'écrit si on l'accepte.

        La même confirmation que pour une phrase tapée : un document apporte
        vingt entrées d'un coup, donc la liste est montrée en entier avant
        d'écrire — c'est ce qui la rend relisable.
        """
        from greffier.adaptateurs import contexte_fichier

        if not appris:
            return
        detail = "\n".join(
            f"  {genre:8} {ecriture}" + (f" — {sens}" if sens else "")
            for ecriture, sens, genre in appris
        )
        if not messagebox.askyesno(
            "Greffier",
            f"{len(appris)} entrée(s) trouvée(s) dans les documents :\n\n"
            f"{detail}\n\nLes ajouter au contexte ?",
        ):
            self._dire("note", "Rien n'a été ajouté au contexte.")
            return
        poses = 0
        for ecriture, sens, genre in appris:
            ajout = (
                contexte_fichier.ajouter_une_personne if genre == "personne"
                else contexte_fichier.ajouter_un_terme
            )
            with contextlib.suppress(OSError):
                if ajout(self.config.chemins.contexte, ecriture, sens):
                    poses += 1
        self._dire("greffier", (
            f"{poses} entrée(s) ajoutée(s) au contexte, "
            f"{len(appris) - poses} déjà connue(s)."
            + (" Le direct les écrira juste dès la prochaine tranche."
               if self._fil_reunion and poses else "")
        ))

    def _renommer_selection(self) -> None:
        """Donne un sujet lisible à la réunion choisie.

        Un libellé, pas un renommage de fichiers : l'identifiant porte la date,
        qui ordonne la liste et date le compte rendu.
        """
        identifiant = self._selection()
        if identifiant is None:
            self.etat_bas.configure(text="Choisis une réunion dans la liste.")
            return
        try:
            gardee = self.depot.lire(identifiant)
        except (OSError, ValueError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        from tkinter import simpledialog

        propose = simpledialog.askstring(
            "Renommer la réunion",
            "Sujet de la réunion :",
            initialvalue=gardee.sujet or sujet_lisible(
                identifiant, self.config.chemins.comptes_rendus / f"{identifiant}.md"
            ),
            parent=self.racine,
        )
        if propose is None:
            return
        gardee.sujet = propose.strip()
        try:
            self.depot.enregistrer(gardee)
        except OSError as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        self._charger_reunions()
        # Vidé, le sujet rend la main au titre du compte rendu : c'est le moyen
        # d'annuler un renommage sans avoir à retrouver le titre d'origine.
        self.etat_bas.configure(
            text=f"Renommée : {gardee.intitule}" if gardee.sujet
            else "Sujet effacé : le titre du compte rendu reprend la main."
        )

    def _oublier_selection(self) -> None:
        """Efface une réunion, après avoir dit exactement ce qui part.

        L'audio est le seul morceau qu'on ne puisse pas refaire : la
        confirmation le nomme et le pèse, plutôt que de demander « supprimer ? »
        sans dire de quoi.
        """
        from greffier.application import ranger

        identifiant = self._selection()
        if identifiant is None:
            self.etat_bas.configure(text="Choisis une réunion dans la liste.")
            return
        ou = self._emplacements()
        pieces = ranger.pieces_de(ou, identifiant)
        if not pieces:
            messagebox.showinfo("Greffier", "Il ne reste rien à effacer pour cette réunion.")
            self._charger_reunions()
            return
        detail = "\n".join(
            f"  {ranger.lisible(p.octets):>8}  {p.quoi}" for p in pieces
        )
        total = ranger.lisible(sum(p.octets for p in pieces))
        if not messagebox.askyesno(
            "Greffier",
            f"Effacer définitivement « {identifiant} » ?\n\n{detail}\n\n"
            f"{total} au total. L'enregistrement audio ne peut pas être refait.",
            default="no",
        ):
            return
        effacees = ranger.oublier(ou, identifiant)
        self._charger_reunions()
        self._charger_voix()
        self.etat_bas.configure(
            text=f"{len(effacees)} fichier(s) effacé(s), "
                 f"{ranger.lisible(sum(p.octets for p in effacees))} libérés."
        )

    def _emplacements(self) -> Any:
        """Où vivent les morceaux d'une réunion, d'après la configuration."""
        from greffier.application.ranger import Emplacements

        chemins = self.config.chemins
        return Emplacements(
            reunions=chemins.donnees / "reunions",
            enregistrements=chemins.enregistrements,
            transcriptions=chemins.transcriptions,
            comptes_rendus=chemins.comptes_rendus,
            direct=chemins.direct,
            propositions=chemins.propositions,
            questions=chemins.questions,
            conversations=chemins.conversations,
            pieces=chemins.pieces,
        )

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
        objet = titre(compte_rendu, f"Compte rendu : {identifiant}")
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
        acte = nommage(self.config)
        try:
            acte.nommer(identifiant, voix, nom)
        except (KeyError, RuntimeError, ValueError, OSError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        self.champ_nom.delete(0, "end")
        self._charger_voix()
        self.etat_bas.configure(text=f"{nom} est en banque.")
        self._dire("greffier", f"{nom} est en banque, et sera reconnue seule aux "
                               "prochaines réunions.")
        # Le seul moment où l'on peut encore se raviser sans effort : après, une
        # empreinte fausse se confirme d'elle-même à chaque réunion.
        if acte.doute:
            self._dire("greffier", acte.doute)
            messagebox.showwarning("Greffier", acte.doute)
        self._regenerer_apres_nommage(identifiant)

    def _signaler_un_paquet_plus_recent(self) -> None:
        """Dit si l'application qui tourne n'est plus celle qui est installée.

        macOS garde en mémoire l'exemplaire lancé : reconstruire ne remplace
        rien tant qu'on n'a pas quitté. Coût mesuré : deux heures passées à
        chercher trois boutons dans une fenêtre ouverte la veille, alors qu'ils
        étaient dans le paquet depuis le matin, et rien ne le disait.
        """
        from greffier.adaptateurs.mises_a_jour import paquet_plus_recent

        if not paquet_plus_recent():
            return
        self._dire(
            "greffier",
            "Une version plus récente de Greffier est installée, mais cette "
            "fenêtre tourne encore sur la précédente. Quitte l'application "
            "(⌘Q) et relance-la pour en profiter.",
        )

    def _signaler_les_reprises(self) -> None:
        """Dit s'il reste une réunion transcrite dont le compte rendu manque.

        Une rédaction interrompue — l'application fermée, la machine endormie,
        le rédacteur qui échoue — ne laissait aucune trace : la transcription
        était sur le disque, le compte rendu n'existait pas, et rien ne le
        remarquait. Une réunion d'une heure quarante a été perdue ainsi.

        On le dit, on ne le fait pas : relancer une rédaction sans qu'on l'ait
        demandé consommerait le quota du rédacteur à l'ouverture de la fenêtre.
        """
        from greffier.application.restituer import a_reprendre

        try:
            restants = a_reprendre(self.depot, self.config.chemins.comptes_rendus)
        except OSError:
            return
        if not restants:
            return
        combien = len(restants)
        pluriel = "s" if combien > 1 else ""
        self._dire(
            "greffier",
            f"{combien} réunion{pluriel} transcrite{pluriel} sans compte rendu : "
            f"{', '.join(restants[:3])}"
            + (f" et {combien - 3} autre{'s' if combien > 4 else ''}"
               if combien > 3 else "")
            + ". Sélectionne-la dans Réunions et clique « Rédiger » : la "
            "transcription est gardée, seule la rédaction reste à refaire.",
        )

    def _oublier_le_nom(self) -> None:
        """Retire le nom d'une voix, après confirmation.

        La confirmation parce que le geste défait un travail : sur une réunion
        où l'on vient de nommer cinq personnes, un clic de trop au mauvais
        endroit se répare mal de mémoire.
        """
        from greffier.composition import nommage

        identifiant, voix = self._selection(), self._voix_selectionnee()
        if not (identifiant and voix):
            messagebox.showinfo("Greffier", "Choisis une réunion, puis une voix.")
            return
        if not messagebox.askyesno(
            "Greffier",
            f"Retirer le nom de la voix {voix} ?\n\n"
            "La réunion l'oublie. L'empreinte déjà versée en banque, elle, "
            "reste : « greffier connus » montre les entrées douteuses.",
        ):
            return
        try:
            nommage(self.config).oublier(identifiant, voix)
        except (KeyError, RuntimeError, ValueError, OSError) as souci:
            messagebox.showerror("Greffier", str(souci))
            return
        self._charger_voix()
        self.etat_bas.configure(text=f"La voix {voix} n'a plus de nom.")

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
            return regenerer_compte_rendu(
                reunion, moteur, self.config.conversation.information
            )

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
        self._garder_le_tour(qui, texte)
        self._peindre_le_tour(qui, texte)

    def _garder_le_tour(self, qui: str, texte: str) -> None:
        """Écrit le tour sous la réunion dont il parle, s'il y en a une.

        Sans réunion identifiable, on ne garde rien : ranger un échange sous
        une réunion au hasard rendrait le fichier trompeur.
        """
        from greffier.adaptateurs import conversations_fichier

        identifiant = self._fil_reunion or self._selection()
        if not identifiant:
            return
        conversations_fichier.ajouter(
            conversations_fichier.fichier_de(self.config.chemins.conversations,
                                             identifiant),
            qui, texte,
        )

    def _peindre_le_tour(self, qui: str, texte: str) -> None:
        self.fil.configure(state="normal")
        if qui in ("moi", "greffier"):
            self.fil.insert("end", "TOI\n" if qui == "moi" else "GREFFIER\n", "qui")
            self.fil.insert("end", f"{texte}\n", "dit")
        else:
            self.fil.insert("end", f"{texte}\n", "note")
        self.fil.see("end")
        self.fil.configure(state="disabled")

    def _repondre_a_la_question(self, reponse: str) -> bool:
        """Traite la saisie comme une réponse à la question en attente.

        Rend Faux si la saisie n'en est manifestement pas une : une phrase
        longue est une nouvelle question, pas une correction d'orthographe, et
        la confondre ferait perdre les deux.
        """
        from greffier.adaptateurs import contexte_fichier, questions_fichier
        from greffier.domaine.intentions import accord

        en_attente = self._questions_attente[0]
        dit = accord(reponse)
        if dit is True:
            retenu = en_attente.question.attendu
        elif dit is False:
            retenu = ""
        elif len(reponse.split()) <= 3:
            # Une orthographe donnée à la main l'emporte : c'est le cas où
            # l'outil s'est trompé de terme, pas seulement d'orthographe.
            retenu = reponse.strip()
        else:
            return False

        self.question.delete(0, "end")
        self._dire("moi", reponse)
        fichier = questions_fichier.fichier_des_questions(
            self.config.chemins.questions, self._fil_reunion
        )
        with contextlib.suppress(OSError):
            questions_fichier.repondre(fichier, en_attente.numero, retenu or "non")
        if retenu:
            with contextlib.suppress(OSError):
                pose = contexte_fichier.ajouter_un_terme(
                    self.config.chemins.contexte, retenu
                )
            self._dire("note", (
                f"« {retenu} » ajouté au contexte : les prochaines réunions "
                "l'écriront juste." if pose
                else f"« {retenu} » était déjà connu."
            ))
        else:
            self._dire("note", "Noté, je ne redemanderai pas.")
        self._questions_attente = self._questions_attente[1:]
        self.onglets.marquer("Conversation", len(self._questions_attente))
        return True

    def _entendre_une_intention(self, phrase: str) -> bool:
        """Reconnaît « retiens que… » et demande confirmation avant d'écrire.

        Reconnu par motifs et non en interrogeant le rédacteur : faire analyser
        chaque phrase tapée coûterait un appel distant, y compris pour une
        question ordinaire. Un motif se trompe, d'où la confirmation — un faux
        positif coûte une question, pas une entrée fausse dans le contexte.
        """
        from greffier.domaine.intentions import comprendre

        appris = comprendre(phrase)
        if appris is None:
            return False
        self._apprentissage_attente = appris
        self.question.delete(0, "end")
        self._dire("moi", phrase)
        self._dire("note", appris.dire())
        return True

    def _confirmer_l_apprentissage(self, reponse: str) -> bool:
        """Écrit dans le contexte si la réponse confirme. Faux si ce n'en est pas une.

        Une phrase qui n'est ni oui ni non est une nouvelle demande : la
        prendre pour un refus la perdrait. L'apprentissage est alors abandonné,
        parce qu'un accord donné trois messages plus tard ne porterait plus sur
        ce qu'on a sous les yeux.
        """
        from greffier.adaptateurs import contexte_fichier
        from greffier.domaine.intentions import Quoi, accord

        dit = accord(reponse)
        if dit is None:
            self._apprentissage_attente = None
            return False
        appris = self._apprentissage_attente
        self._apprentissage_attente = None
        self.question.delete(0, "end")
        self._dire("moi", reponse)
        if not dit:
            self._dire("note", "Rien n'a été écrit.")
            return True

        ajout = (
            contexte_fichier.ajouter_une_personne if appris.quoi is Quoi.PERSONNE
            else contexte_fichier.ajouter_un_terme
        )
        pose = False
        with contextlib.suppress(OSError):
            pose = ajout(self.config.chemins.contexte, appris.sujet, appris.precision)
        if not pose:
            self._dire("note", f"« {appris.sujet} » était déjà dans le contexte.")
            return True
        # Le direct relit le contexte à chaque tranche : ce qui est appris
        # maintenant sert à la phrase suivante, pas à la réunion d'après.
        self._dire("greffier", (
            f"« {appris.sujet} » ajouté au contexte. La transcription en cours "
            "l'écrira juste dès la prochaine tranche."
            if self._fil_reunion else
            f"« {appris.sujet} » ajouté au contexte."
        ))
        return True

    def _avec_les_documents(self, matiere: str, identifiant: str) -> str:
        """Ajoute à la matière le texte des documents fournis pour cette réunion."""
        from greffier.adaptateurs import pieces_fichier

        documents = pieces_fichier.matiere(self.config.chemins.pieces, identifiant)
        if not documents:
            return matiere
        return (
            f"{matiere}\n\n--- Documents fournis pour cette réunion ---\n{documents}"
        )

    def _fournir_un_document(self) -> None:
        """Donne un document à l'outil pendant la réunion, en un geste, deux effets.

        Le texte reste attaché à la réunion, donc l'assistant répond dessus ;
        et le vocabulaire qu'il porte est proposé au contexte, donc les
        tranches suivantes du direct l'écrivent juste. Les deux comptent : un
        ordre du jour fourni en début de réunion nomme la moitié des sigles
        qu'on va entendre.
        """
        from tkinter import filedialog

        from greffier.adaptateurs import pieces_fichier
        from greffier.application import deposer as travail
        from greffier.domaine.depot import Destin, proposer

        choisis = filedialog.askopenfilenames(
            parent=self.racine,
            title="Fournir des documents pour cette réunion",
        )
        if not choisis:
            return
        outils = travail.outils_presents()
        propositions = [
            proposer(Path(chemin), Path(chemin).stat().st_size, outils)
            for chemin in choisis
        ]
        documents = [p for p in propositions if p.destin is Destin.CONTEXTE]
        autres = [p for p in propositions if p.destin is not Destin.CONTEXTE]
        if autres:
            self._dire("note", (
                f"{len(autres)} fichier(s) sont des sons ou des vidéos : ils "
                "deviennent des réunions à transcrire, pas du contexte. "
                "Onglet Réunions, « Déposer des fichiers »."
            ))
        if not documents:
            return

        identifiant = self._fil_reunion or self._selection() or ""
        if not identifiant:
            self._dire("note", (
                "Aucune réunion en cours ni choisie : je lis quand même les "
                "documents pour en tirer du vocabulaire, mais leur texte ne "
                "sera rangé sous aucune réunion."
            ))
        redacteur = self._redacteur_de_documents(documents)

        def faire(dire: Callable[[str], None]) -> Any:
            gardees: list[Any] = []
            appris: list[tuple[str, str, str]] = []
            soucis: list[str] = []
            for numero, proposition in enumerate(documents, start=1):
                dire(f"{proposition.fichier.name} ({numero}/{len(documents)})…")
                lu = travail.lire_le_texte(proposition.fichier)
                if not lu.strip():
                    soucis.append(proposition.fichier.name)
                    continue
                if identifiant:
                    piece = pieces_fichier.ecrire(
                        self.config.chemins.pieces, identifiant,
                        proposition.fichier.name, lu,
                    )
                    if piece is not None:
                        gardees.append(piece)
                if redacteur is not None:
                    appris.extend(travail.apprendre_du_texte(lu, redacteur))
            return (gardees, appris, soucis)

        def fini(rendu: Any, souci: Exception | None) -> None:
            if souci is not None:
                self._dire("note", f"Lecture interrompue : {souci}")
                return
            gardees, appris, soucis = rendu
            for nom in soucis:
                self._dire("note", (
                    f"{nom} : rien de lisible. Un PDF scanné demande "
                    "« pdftotext », et une image n'est pas du texte."
                ))
            for piece in gardees:
                self._dire("greffier", (
                    f"« {piece.nom} » lu, {piece.caracteres} caractères gardés. "
                    "Tu peux me poser des questions dessus."
                ))
            self._proposer_au_contexte(appris)

        self._lancer(Travail(intitule="lecture", faire=faire, fini=fini))

    def _demander(self) -> None:
        from greffier.composition import assistant

        question = self.question.get().strip()
        if not question:
            return
        # Une question en attente prend la main sur la conversation : ce qu'on
        # tape répond à ce qui vient d'être demandé, comme dans un dialogue.
        # Autrement, il faudrait un second champ de saisie pour la même chose.
        if self._questions_attente and self._repondre_a_la_question(question):
            return
        if self._apprentissage_attente is not None and self._confirmer_l_apprentissage(
            question
        ):
            return
        if self._entendre_une_intention(question):
            return

        moteur = assistant(self.config)
        if moteur is None:
            self._dire("note", "Aucun rédacteur configuré : « greffier configurer ».")
            return

        # Le fil de la réunion en cours d'abord : demander « qu'a-t-on décidé
        # sur Oasis ? » pendant qu'on en parle était impossible, la conversation
        # exigeant un compte rendu, donc une réunion terminée. Le fil, lui, est
        # déjà là.
        en_cours = self._fil.rendu() if self._fil_reunion else ""
        if en_cours:
            matiere, quoi, sur = en_cours, "la transcription en direct", self._fil_reunion
        else:
            identifiant = self._selection()
            if identifiant is None:
                self._dire("note", "Choisis une réunion dans l'onglet Réunions, "
                                   "ou démarre une réunion pour interroger le direct.")
                return
            source = self.config.chemins.comptes_rendus / f"{identifiant}.md"
            if not source.exists():
                self._dire("note", f"« {identifiant} » n'a pas encore de compte rendu. "
                                   "Onglet Réunions, « Traiter ».")
                return
            matiere, quoi, sur = source.read_text(encoding="utf-8"), "le compte rendu", identifiant

        matiere = self._avec_les_documents(matiere, sur)
        self.question.delete(0, "end")
        self._dire("moi", question)

        def faire(dire: Callable[[str], None]) -> Any:
            dire("réflexion…")
            # Les consignes viennent de l'assistant : les écrire ici les
            # dupliquerait, et c'est lui qui sait s'il a le droit de chercher.
            return moteur.rediger(
                f"Question : {question}\n\n"
                f"Ce qui a été dit — {quoi} de la réunion « {sur} » :\n{matiere}"
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
        # Après le premier tour de boucle : signaler avant que la fenêtre ne
        # soit peinte n'afficherait rien.
        self.racine.after(600, self._signaler_les_redactions_manquantes)
        self.racine.after(900, self._rappeler_l_information)
        self.racine.mainloop()

    def _rappeler_l_information(self) -> None:
        """Rappelle une fois par session que les participants doivent savoir.

        Une fois, et dans la conversation : une mention qu'on lit avant chaque
        réunion devient un bouton qu'on clique sans lire. Le compte rendu
        portera de toute façon la phrase qui dit ce qui a été fait, y compris
        « rien n'a été tracé ».
        """
        from greffier.domaine.consentement import RAPPEL, a_tracer, lire

        if a_tracer(lire(self.config.conversation.information)):
            self._peindre_le_tour("greffier", RAPPEL)

    def _signaler_les_redactions_manquantes(self) -> None:
        """Dit quelles réunions attendent encore leur compte rendu.

        Une rédaction qui échoue laissait une réunion transcrite sur le disque
        et personne pour y penser : il fallait remarquer soi-même qu'un compte
        rendu n'était jamais arrivé, ce qui prend des heures ou des jours. La
        liste le montre colonne « Compte rendu », mais rien ne le portait à
        l'attention.
        """
        from greffier.domaine.reunion import tenue_le

        with contextlib.suppress(OSError, ValueError):
            manquantes = [
                identifiant
                for identifiant in self.depot.lister()[:20]
                # Seules les réunions **datées** : les enregistrements d'essai
                # fabriqués par « outils/fabriquer_reunion.py » n'ont pas de
                # compte rendu et n'en attendent pas. Les signaler noyait le
                # message sous cinq faux positifs, constaté à l'usage.
                if tenue_le(identifiant) is not None
                and not (self.config.chemins.comptes_rendus / f"{identifiant}.md").exists()
                and bool(self.depot.lire(identifiant).repliques)
            ]
            if not manquantes:
                return
            pluriel = "s" if len(manquantes) > 1 else ""
            # Peint et non « dit » : un état général de l'outil n'appartient à
            # la conversation d'aucune réunion, et s'y inscrire salissait le
            # journal de celle qui se trouvait sélectionnée.
            self._peindre_le_tour("greffier", (
                f"{len(manquantes)} réunion{pluriel} transcrite{pluriel} sans compte "
                f"rendu : {', '.join(manquantes[:3])}"
                + ("…" if len(manquantes) > 3 else "")
                + ". Onglet Réunions, « Rédiger » reprend la rédaction sans "
                "retranscrire."
            ))
            self.onglets.marquer("Conversation", len(manquantes))

def ouvrir(config: Config) -> None:
    """Point d'entrée de la fenêtre."""
    Fenetre(config).tourner()
