"""Demander à GitHub s'il existe une version postérieure à celle installée.

Le seul appel réseau de l'outil en dehors de la rédaction, et il est
facultatif : rien ne dépend de lui, une panne de réseau ne coûte que
l'information. Il vise l'API publique des releases, sans jeton — le dépôt est
public, et demander une authentification pour savoir s'il existe une mise à
jour serait absurde.

Ce module ne décide de rien : il rapporte ce que le service répond, et la
comparaison appartient au domaine. Il n'installe rien non plus : remplacer une
application pendant qu'elle tourne est un problème distinct, qui mérite d'être
traité séparément et non en effet de bord d'une vérification.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as version_du_paquet
from pathlib import Path
from typing import Any

from greffier.domain.version import is_newer

REPOSITORY = "tanguychenier/greffier"

TIMEOUT = 5.0

DELAI_TELECHARGEMENT = 600.0

ARTEFACTS = {
    "Darwin": "Greffier-macos.zip",
    "Windows": "Greffier-windows.zip",
    "Linux": "Greffier-linux.tar.gz",
}

@dataclass(frozen=True, slots=True)
class Verdict:
    """Ce que la vérification a appris. `souci` renseigné, rien n'est sûr."""

    installed: str
    available: str = ""
    adresse: str = ""
    trouble: str = ""
    artefact: str = ""
    artefact_nom: str = ""

    @property
    def downloadable(self) -> bool:
        """Vrai quand il existe un binaire à installer pour ce poste."""
        return bool(self.available and self.artefact)

    @property
    def up_to_date(self) -> bool:
        return not self.trouble and not self.available

    @property
    def update(self) -> bool:
        return bool(self.available)

    def say(self) -> str:
        """Une phrase pour l'écran, en français, sans jargon."""
        if self.trouble:
            return f"Vérification impossible : {self.trouble}"
        if self.available:
            return f"Version {self.available} disponible (vous avez {self.installed})."
        return f"À jour : version {self.installed}."

def installed_version() -> str:
    """La version du paquet en place, ou une chaîne vide si elle est illisible.

    Lue depuis les métadonnées du paquet plutôt qu'écrite en dur : deux
    endroits qui portent un numéro finissent par se contredire, et c'est
    justement ce qu'on cherche à comparer.
    """
    try:
        installed = version_du_paquet("greffier")
    except PackageNotFoundError:
        installed = ""
    depuis_les_sources = _version_du_projet()
    return depuis_les_sources or installed

def _version_du_projet() -> str:
    """La version écrite dans `pyproject.toml`, si on tourne depuis les sources.

    Vide dès que le fichier n'est pas là, ce qui est le cas dans le paquet
    construit : la question ne se pose alors pas.
    """
    projet = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if not projet.exists():
        return ""
    try:
        import tomllib

        with projet.open("rb") as flux:
            return str(tomllib.load(flux).get("project", {}).get("version", ""))
    except (OSError, ValueError):
        return ""

def build_repository() -> Path | None:
    """Le dépôt d'où ce paquet a été fabriqué, s'il est encore là.

    Gravé par `construire.sh`. L'application n'en dépend pas pour fonctionner :
    on ne s'en sert que pour installer une mise à jour, et son absence ne coûte
    que ce bouton.
    """
    grave = os.environ.get("GREFFIER_DEPOT_SOURCE", "").strip()
    if not grave:
        return None
    path = Path(grave)
    return path if (path / "macos" / "construire.sh").exists() else None

def installable() -> tuple[bool, str]:
    """Peut-on installer d'ici ? Sinon, pourquoi.

    Refuse dès que l'arbre du dépôt porte des modifications non validées : une
    mise à jour n'a pas à emporter le travail en cours de qui développe, et un
    « git pull » sur un arbre sale échoue de toute façon, à moitié.
    """
    store = build_repository()
    if store is None:
        return (False, "le dépôt d'origine est introuvable")
    if shutil.which("git") is None:
        return (False, "git est introuvable")
    state = subprocess.run(
        ["git", "-C", str(store), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    if state.returncode != 0:
        return (False, "ce dossier n'est pas un dépôt git")
    if state.stdout.strip():
        return (False, "le dépôt porte des modifications non validées")
    return (True, str(store))

_RELAIS = """#!/bin/bash
set -u
exec >>"$3" 2>&1
echo "=== mise à jour lancée le $(date '+%Y-%m-%d %H:%M:%S') ==="
for _ in $(seq 1 60); do
  kill -0 "$2" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$2" 2>/dev/null; then
  echo "✗ l'application n'a pas quitté : rien n'a été touché"
  exit 1
fi
cd "$1" || exit 1
git pull --ff-only || { echo "✗ git pull a échoué : le paquet est intact"; exit 1; }
bash macos/construire.sh || { echo "✗ la reconstruction a échoué"; exit 1; }
echo "✓ mis à jour, relancement"
open -a "$4"
"""

def install(app: str = "Greffier") -> tuple[bool, str]:
    """Lance le relais de mise à jour, puis rend la main pour qu'on se ferme.

    Ne met rien à jour par elle-même : elle prépare, et c'est l'appelant qui
    doit quitter juste après. Le relais attend la fin du processus avant de
    toucher au paquet.
    """
    possible, because = installable()
    if not possible:
        return (False, because)

    log = Path.home() / "Library" / "Logs" / "Greffier-maj.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    script = Path(tempfile.gettempdir()) / "greffier-mise-a-jour.sh"
    script.write_text(_RELAIS, encoding="utf-8")
    script.chmod(0o755)
    try:
        subprocess.Popen(
            ["/bin/bash", str(script), because, str(os.getpid()), str(log), app],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as trouble:
        return (False, str(trouble))
    return (True, str(log))

def bundle_of_this_process(argv0: str = "") -> Path | None:
    """Le paquet .app depuis lequel ce processus tourne, s'il y en a un.

    Rend rien hors du paquet : depuis la ligne de commande, il n'y a pas
    d'application à remplacer.
    """
    executable = Path(argv0 or sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent
    return None

def download(
    url: str, target: Path, timeout: float = DELAI_TELECHARGEMENT,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[bool, str]:
    """Écrit l'artefact sur le disque. Ne lève jamais.

    Par morceaux, et en rapportant l'avancement : on télécharge cent cinquante
    mégaoctets, et une fenêtre qui se figeait sans rien dire pendant deux
    minutes passait pour cassée.
    """
    requete = urllib.request.Request(url, headers={"User-Agent": "Greffier"})
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(requete, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            recu = 0
            with target.open("wb") as output:
                while morceau := response.read(262144):
                    output.write(morceau)
                    recu += len(morceau)
                    if progress is not None:
                        progress(recu, total)
    except (urllib.error.URLError, TimeoutError):
        return (False, "pas de réseau")
    except (OSError, ValueError) as trouble:
        return (False, str(trouble))
    if target.stat().st_size == 0:
        return (False, "archive vide")
    return (True, str(target))

def unpack(archive: Path, folder: Path) -> tuple[bool, str]:
    """Ouvre l'archive dans un dossier. Rend le chemin de ce qu'elle contient.

    Zip pour macOS et Windows, tar pour Linux : le format vient du nom, pas
    d'une devinette sur le contenu.
    """
    import tarfile
    import zipfile

    try:
        folder.mkdir(parents=True, exist_ok=True)
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(folder)
        elif archive.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive) as a:
                a.extractall(folder, filter="data")
        else:
            return (False, f"format inconnu : {archive.name}")
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as trouble:
        return (False, str(trouble))
    return (True, str(folder))

_RELAIS_BINAIRE = """#!/bin/bash
set -u
exec >>"$3" 2>&1
echo "=== mise a jour binaire lancee le $(date '+%Y-%m-%d %H:%M:%S') ==="
NEUF="$1"; PID="$2"; APP="$4"
for _ in $(seq 1 120); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$PID" 2>/dev/null; then
  echo "x l'application n'a pas quitte : rien n'a ete touche"
  exit 1
fi
[ -d "$NEUF" ] || { echo "x le paquet telecharge est introuvable"; exit 1; }
DE_COTE="$APP.precedent"
rm -rf "$DE_COTE"
mv "$APP" "$DE_COTE" 2>/dev/null || true
if ! mv "$NEUF" "$APP"; then
  echo "x remplacement impossible, ancienne version remise"
  mv "$DE_COTE" "$APP" 2>/dev/null || true
  exit 1
fi
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$APP" 2>/dev/null
open -a "$APP" || true
for _ in $(seq 1 24); do
  pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1 && break
  sleep 0.5
done
if pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; then
  echo "v mis a jour et relance"
  rm -rf "$DE_COTE"
else
  echo "x la nouvelle version ne demarre pas, ancienne version remise"
  rm -rf "$APP"
  mv "$DE_COTE" "$APP" 2>/dev/null || true
  open -a "$APP" || true
  exit 1
fi
"""

def install_from_release(
    verdict: Verdict, argv0: str = "",
    progress: Callable[[int, int], None] | None = None,
) -> tuple[bool, str]:
    """Télécharge l'artefact de ce système et le met en place.

    C'est le chemin de qui n'a pas le dépôt : la très grande majorité. Rien
    n'est compilé, rien n'est cloné — on prend l'archive publiée pour ce
    système, on l'ouvre, et un relais remplace le paquet après la fermeture.

    Hors macOS, l'archive est téléchargée et son chemin rendu : remplacer un
    exécutable Windows qui tourne, ou réinstaller des sources sous Linux,
    demande autre chose qu'un `mv`, et prétendre le faire serait pire que le
    dire.
    """
    if not verdict.downloadable:
        return (False, "aucun binaire publié pour ce système")
    atelier = Path(tempfile.mkdtemp(prefix="greffier-maj."))
    archive = atelier / verdict.artefact_nom
    recu, ou = download(verdict.artefact, archive, progress=progress)
    if not recu:
        return (False, ou)
    ouvert, trouble = unpack(archive, atelier / "contenu")
    if not ouvert:
        return (False, trouble)

    if platform.system() != "Darwin":
        return (True, str(atelier / "contenu"))

    paquets = list((atelier / "contenu").glob("*.app"))
    if not paquets:
        return (False, "l'archive ne contient pas d'application")
    app = bundle_of_this_process(argv0)
    if app is None:
        return (False, "cette version ne tourne pas depuis un paquet")

    log = Path.home() / "Library" / "Logs" / "Greffier-maj.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    script = Path(tempfile.gettempdir()) / "greffier-maj-binaire.sh"
    script.write_text(_RELAIS_BINAIRE, encoding="utf-8")
    script.chmod(0o755)
    try:
        subprocess.Popen(
            ["/bin/bash", str(script), str(paquets[0]), str(os.getpid()),
             str(log), str(app)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as trouble:
        return (False, str(trouble))
    return (True, str(log))

def bundle_is_newer(argv0: str = "") -> bool:
    """Le paquet sur le disque est-il plus récent que le processus qui tourne ?

    Un paquet reconstruit ne remplace pas l'application déjà lancée, et rien ne
    le disait. Coût mesuré : deux heures passées à chercher trois boutons dans
    une fenêtre ouverte la veille, alors qu'ils étaient dans le paquet depuis le
    matin. La fenêtre a maintenant de quoi le dire.

    Rend faux hors du paquet — depuis la ligne de commande, le code suit le
    dépôt et la question ne se pose pas.
    """

    executable = Path(argv0 or sys.executable)
    if "/Contents/MacOS/" not in str(executable):
        return False
    try:
        pose = executable.stat().st_mtime
        return pose > _CHARGE_LE
    except OSError:
        return False

_CHARGE_LE = time.time()

def check(store: str = REPOSITORY, timeout: float = TIMEOUT) -> Verdict:
    """Interroge la dernière release publiée. Ne lève jamais.

    Une vérification de mise à jour qui fait tomber la fenêtre serait un très
    mauvais échange : tout ce qui peut échouer est rapporté dans `souci`.
    """
    installed = installed_version()
    if not installed:
        return Verdict(installed="", trouble="version installée inconnue")

    adresse = f"https://api.github.com/repos/{store}/releases/latest"
    requete = urllib.request.Request(
        adresse,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Greffier"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as response:
            content = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as trouble:
        if trouble.code == 404:
            return Verdict(installed=installed, trouble="aucune version publiée")
        return Verdict(installed=installed, trouble=f"réponse {trouble.code} de GitHub")
    except (urllib.error.URLError, TimeoutError):
        return Verdict(installed=installed, trouble="pas de réseau")
    except (ValueError, OSError) as trouble:
        return Verdict(installed=installed, trouble=str(trouble))

    if not isinstance(content, dict):
        return Verdict(installed=installed, trouble="réponse inattendue")
    label = str(content.get("tag_name", "")).strip()
    if not label:
        return Verdict(installed=installed, trouble="version publiée sans étiquette")
    if not is_newer(label, installed):
        return Verdict(installed=installed)
    name, url = _artifact_for_this_system(content)
    return Verdict(
        installed=installed,
        available=label.lstrip("v"),
        adresse=str(content.get("html_url", "")),
        artefact=url,
        artefact_nom=name,
    )

def _artifact_for_this_system(publication: dict[str, Any]) -> tuple[str, str]:
    """Le nom et l'adresse de l'artefact qui convient à ce système.

    Le bon et aucun autre : les trois sont attachés à la même version, et une
    archive Windows installée sur un Mac ne produirait rien de lançable.
    """
    attendu = ARTEFACTS.get(platform.system(), "")
    if not attendu:
        return ("", "")
    for piece in publication.get("assets") or []:
        if not isinstance(piece, dict):
            continue
        if str(piece.get("name", "")) == attendu:
            return (attendu, str(piece.get("browser_download_url", "")))
    return ("", "")
