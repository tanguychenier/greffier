"""Fabriquer une sauvegarde, et savoir la restaurer.

Une archive par sauvegarde, en `.tar.gz`, nommée par sa date. Une archive et
non un dossier copié : elle se déplace d'un geste vers un disque externe ou un
espace partagé, et c'est ce déplacement qui fait la sauvegarde — une copie
laissée sur le même disque ne protège que de l'effacement accidentel, pas de la
perte du disque. Le dossier de destination est donc réglable, et le message le
dit quand il vaut le défaut.

Restaurer est l'autre moitié du travail, et la moitié qu'on oublie : une
sauvegarde qu'on n'a jamais restaurée est une hypothèse. `restaurer` existe
donc, elle refuse d'écraser sans qu'on le demande, et un test la rejoue.
"""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from greffier.domain.backup import CONTENT, KEPT, Nom, to_erase


@dataclass(frozen=True, slots=True)
class Faite:
    """Ce qu'une sauvegarde a emporté."""

    archive: Path
    dossiers: tuple[str, ...]
    files: int
    bytes_read: int
    effacees: tuple[str, ...] = ()
    data: Path | None = None

    @property
    def on_the_same_disk(self) -> bool:
        """Vrai si l'archive est restée sous ce qu'elle sauvegarde.

        À dire à l'utilisateur : cela protège d'un effacement accidentel, pas
        de la perte du disque, et confondre les deux est la façon habituelle de
        n'avoir aucune sauvegarde le jour où il en faut une.

        Comparé au dossier de données réel, et non en cherchant un mot dans le
        chemin : « Greffier-sauvegardes » dans un espace synchronisé contient le
        mot « Greffier » et déclenchait l'avertissement à tort, ce qui est la
        pire façon de se tromper — on prévient qui a fait ce qu'il fallait.
        """
        if self.data is None:
            return False
        try:
            self.archive.parent.resolve().relative_to(self.data.resolve())
        except (ValueError, OSError):
            return False
        return True

def do_it(
    data: Path,
    config: Path | None,
    destination: Path,
    kept: int = KEPT,
    quand: datetime | None = None,
) -> Faite:
    """Écrit l'archive et applique la rotation. Rend ce qui a été fait.

    Les dossiers absents sont sautés sans bruit : une installation neuve n'a ni
    conversations ni questions, et ce n'est pas une anomalie.
    """
    name = Nom(quand or datetime.now(UTC).astimezone())
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{name}.tar.gz"

    pris: list[str] = []
    files = 0
    # Écrite à côté puis renommée : une archive interrompue ne doit pas prendre
    # la place d'une archive valable, et surtout ne doit pas passer pour telle.
    temporary = archive.with_suffix(".partiel")
    try:
        with tarfile.open(temporary, "w:gz") as tar:
            for folder in CONTENT:
                source = data / folder
                if not source.exists():
                    continue
                tar.add(source, arcname=folder)
                pris.append(folder)
                files += sum(1 for _ in source.rglob("*") if _.is_file())
            # La configuration et les registres tenus à la main : ils vivent
            # ailleurs que les données, et se réécrire à la main est justement
            # ce qu'on veut éviter.
            if config is not None and config.exists():
                for file in ("config.toml", "contexte.toml", "sujets.toml"):
                    path = config / file
                    if path.exists():
                        tar.add(path, arcname=f"configuration/{file}")
                        files += 1
                pris.append("configuration")
        temporary.replace(archive)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    effacees: list[str] = []
    for vieille in to_erase(
        [path.name.removesuffix(".tar.gz")
         for path in destination.glob("greffier-*.tar.gz")],
        kept,
    ):
        path = destination / f"{vieille}.tar.gz"
        try:
            path.unlink()
            effacees.append(vieille)
        except OSError:
            continue

    return Faite(archive, tuple(pris), files,
                 archive.stat().st_size, tuple(effacees), data=data)

def restore(archive: Path, data: Path, ecraser: bool = False) -> list[str]:
    """Remet une sauvegarde en place. Rend les dossiers restaurés.

    Refuse par défaut d'écraser ce qui existe : restaurer par erreur une
    sauvegarde de la semaine dernière par-dessus le travail du jour ferait plus
    de dégâts que la panne qu'on voulait réparer.
    """
    if not archive.exists():
        raise FileNotFoundError(f"archive introuvable : {archive}")
    with tarfile.open(archive, "r:gz") as tar:
        racines = sorted({
            membre.name.split("/")[0] for membre in tar.getmembers()
            if "/" in membre.name or membre.isdir()
        })
        if not ecraser:
            deja = [name for name in racines if (data / name).exists()]
            if deja:
                raise FileExistsError(
                    "déjà présent, et rien n'a été touché : "
                    + ", ".join(deja)
                    + ". Relance en demandant explicitement d'écraser."
                )
        data.mkdir(parents=True, exist_ok=True)
        # `filter="data"` : une archive de sauvegarde ne doit pas pouvoir écrire
        # hors du dossier de destination, même la sienne.
        tar.extractall(data, filter="data")
    return racines

def lister(destination: Path) -> list[tuple[str, int, datetime]]:
    """Les sauvegardes présentes, la plus récente d'abord."""
    trouvees: list[tuple[str, int, datetime]] = []
    if not destination.exists():
        return trouvees
    for path in destination.glob("greffier-*.tar.gz"):
        quand = Nom.read(path.name.removesuffix(".tar.gz"))
        if quand is None:
            continue
        trouvees.append((path.name, path.stat().st_size, quand))
    return sorted(trouvees, key=lambda line: line[2], reverse=True)

def space_available(destination: Path) -> int:
    """Octets libres là où l'on écrit. Zéro si on ne sait pas."""
    try:
        return shutil.disk_usage(destination).free
    except OSError:
        return 0
