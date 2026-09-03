"""Où Greffier range sa configuration et ses données, selon le système.

Sans dépendance : l'installeur charge ce module *avant* que quoi que ce soit ne
soit installé, avec le Python 3.9 que certains postes livrent encore.

Sur macOS, l'emplacement natif — ``~/Library/Application Support/Greffier`` —
et non la convention XDG. Les dossiers cachés du compte (``~/.config``,
``~/.local``) sont surveillés par les gardes du poste (WithSecure XFENCE), qui
redemandaient une autorisation pour chaque accès de chaque programme de la
chaîne, à chaque réunion ; une écriture y a même été refusée en pleine réunion,
et le direct s'est arrêté net. Application Support est l'endroit où toutes les
applications écrivent : personne ne le conteste. ``XDG_CONFIG_HOME`` et
``XDG_DATA_HOME``, s'ils sont posés, l'emportent — c'est ce qui isole les
tests, et ce qui laisse le choix à qui préfère XDG.

Les anciens emplacements restent servis tant qu'ils existent et que le nouveau
est vide : un poste déjà installé continue de fonctionner. L'installeur les
déménage (`demenager`), pour qu'il ne reste rien dans les dossiers cachés.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import sys
from pathlib import Path

NATIF_MACOS = "Library/Application Support/Greffier"
#: Ce qui fait qu'un dossier « contient une configuration ».
FICHIERS_CONFIG = ("config.toml", ".env")


def _systeme(systeme: str | None) -> str:
    return systeme or platform.system()


def ancien_dossier_config() -> Path:
    return Path.home() / ".config/greffier"


def ancien_dossier_donnees() -> Path:
    return Path.home() / ".local/share/greffier"


def dossier_config(systeme: str | None = None) -> Path:
    systeme = _systeme(systeme)
    if systeme == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "greffier"
    if systeme == "Darwin" and "XDG_CONFIG_HOME" not in os.environ:
        natif = Path.home() / NATIF_MACOS
        ancien = ancien_dossier_config()
        # Jugé au fichier, pas au dossier : les données vivent déjà dans le
        # même dossier natif, qui existe donc sans qu'aucune configuration n'y
        # soit encore.
        if not _contient_configuration(natif) and _contient_configuration(ancien):
            return ancien
        return natif
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "greffier"


def dossier_donnees(systeme: str | None = None) -> Path:
    systeme = _systeme(systeme)
    if systeme == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "greffier"
    if systeme == "Darwin" and "XDG_DATA_HOME" not in os.environ:
        natif = Path.home() / NATIF_MACOS
        ancien = ancien_dossier_donnees()
        if not natif.exists() and ancien.exists():
            return ancien
        return natif
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "greffier"


def _contient_configuration(dossier: Path) -> bool:
    return any((dossier / nom).exists() for nom in FICHIERS_CONFIG)


def demenager(systeme: str | None = None) -> list[tuple[Path, Path]]:
    """Sort des dossiers cachés ce qu'une version précédente y a laissé.

    macOS seulement, et seulement hors XDG. Renvoie les déplacements faits,
    dans l'ordre. Relançable : sans rien à déplacer, ne fait rien. Ce qui existe
    déjà à destination n'est jamais écrasé — l'ancien reste alors en place, et
    son absence de la liste le dit.
    """
    if _systeme(systeme) != "Darwin":
        return []
    natif = Path.home() / NATIF_MACOS
    faits: list[tuple[Path, Path]] = []
    if "XDG_DATA_HOME" not in os.environ:
        faits += _deplacer_contenu(ancien_dossier_donnees(), natif)
    if "XDG_CONFIG_HOME" not in os.environ:
        faits += _deplacer_contenu(ancien_dossier_config(), natif)
    return faits


def _deplacer_contenu(ancien: Path, natif: Path) -> list[tuple[Path, Path]]:
    if not ancien.is_dir():
        return []
    natif.mkdir(parents=True, exist_ok=True)
    faits = []
    for source in sorted(ancien.iterdir()):
        cible = natif / source.name
        if cible.exists() or cible.is_symlink():
            continue
        # shutil.move et non rename : un XDG_DATA_HOME sur un autre volume
        # n'est pas le cas courant, mais un déménagement ne doit pas échouer
        # pour ça.
        shutil.move(str(source), str(cible))
        faits.append((source, cible))
    # Le dossier vide ne doit pas rester : c'est son existence qui ferait
    # croire à une ancienne installation.
    with contextlib.suppress(OSError):
        ancien.rmdir()
    return faits


def situer_tcl(environnement: dict[str, str] | None = None, prefixe: Path | None = None) -> None:
    """Dit à Tcl où sont ses fichiers, quand l'interpréteur l'a oublié.

    Les interpréteurs distribués par uv portent le chemin de la machine qui les
    a compilés : `tk.Tk()` cherche `init.tcl` dans `/tools/deps/lib/tcl9.0`, qui
    n'existe sur aucun poste, et échoue par « This probably means that Tcl
    wasn't installed properly » alors que Tcl est là, à côté de l'interpréteur.

    Mesuré : la fenêtre ne s'ouvrait pas depuis `.venv/bin/greffier`, alors
    qu'elle s'ouvrait depuis le paquet macOS — qui embarque ses propres copies
    et n'a donc jamais rencontré le défaut.

    On ne touche à rien quand les variables sont déjà posées : un poste qui a un
    Tcl du système, ou une distribution qui s'y retrouve seule, garde le sien.
    """
    env = environnement if environnement is not None else os.environ
    racine = prefixe or Path(sys.base_prefix)
    for variable, motif in (("TCL_LIBRARY", "tcl"), ("TK_LIBRARY", "tk")):
        if env.get(variable):
            continue
        candidats = sorted((racine / "lib").glob(f"{motif}[0-9]*.[0-9]*"))
        dossiers = [c for c in candidats if c.is_dir()]
        if dossiers:
            env[variable] = str(dossiers[-1])
