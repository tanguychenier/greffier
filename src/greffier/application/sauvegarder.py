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

from greffier.domaine.sauvegarde import CONTENU, GARDEES, Nom, a_effacer


@dataclass(frozen=True, slots=True)
class Faite:
    """Ce qu'une sauvegarde a emporté."""

    archive: Path
    dossiers: tuple[str, ...]
    fichiers: int
    octets: int
    effacees: tuple[str, ...] = ()

    @property
    def sur_le_meme_disque(self) -> bool:
        """Vrai si l'archive est restée à côté de ce qu'elle sauvegarde.

        À dire à l'utilisateur : cela protège d'un effacement accidentel, pas
        de la perte du disque, et confondre les deux est la façon habituelle de
        n'avoir aucune sauvegarde le jour où il en faut une.
        """
        return "Greffier" in str(self.archive.parent)


def faire(
    donnees: Path,
    config: Path | None,
    destination: Path,
    gardees: int = GARDEES,
    quand: datetime | None = None,
) -> Faite:
    """Écrit l'archive et applique la rotation. Rend ce qui a été fait.

    Les dossiers absents sont sautés sans bruit : une installation neuve n'a ni
    conversations ni questions, et ce n'est pas une anomalie.
    """
    nom = Nom(quand or datetime.now(UTC).astimezone())
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{nom}.tar.gz"

    pris: list[str] = []
    fichiers = 0
    # Écrite à côté puis renommée : une archive interrompue ne doit pas prendre
    # la place d'une archive valable, et surtout ne doit pas passer pour telle.
    provisoire = archive.with_suffix(".partiel")
    try:
        with tarfile.open(provisoire, "w:gz") as tar:
            for dossier in CONTENU:
                source = donnees / dossier
                if not source.exists():
                    continue
                tar.add(source, arcname=dossier)
                pris.append(dossier)
                fichiers += sum(1 for _ in source.rglob("*") if _.is_file())
            # La configuration et les registres tenus à la main : ils vivent
            # ailleurs que les données, et se réécrire à la main est justement
            # ce qu'on veut éviter.
            if config is not None and config.exists():
                for fichier in ("config.toml", "contexte.toml", "sujets.toml"):
                    chemin = config / fichier
                    if chemin.exists():
                        tar.add(chemin, arcname=f"configuration/{fichier}")
                        fichiers += 1
                pris.append("configuration")
        provisoire.replace(archive)
    except BaseException:
        provisoire.unlink(missing_ok=True)
        raise

    effacees: list[str] = []
    for vieille in a_effacer(
        [chemin.name.removesuffix(".tar.gz")
         for chemin in destination.glob("greffier-*.tar.gz")],
        gardees,
    ):
        chemin = destination / f"{vieille}.tar.gz"
        try:
            chemin.unlink()
            effacees.append(vieille)
        except OSError:
            continue

    return Faite(archive, tuple(pris), fichiers,
                 archive.stat().st_size, tuple(effacees))


def restaurer(archive: Path, donnees: Path, ecraser: bool = False) -> list[str]:
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
            deja = [nom for nom in racines if (donnees / nom).exists()]
            if deja:
                raise FileExistsError(
                    "déjà présent, et rien n'a été touché : "
                    + ", ".join(deja)
                    + ". Relance en demandant explicitement d'écraser."
                )
        donnees.mkdir(parents=True, exist_ok=True)
        # `filter="data"` : une archive de sauvegarde ne doit pas pouvoir écrire
        # hors du dossier de destination, même la sienne.
        tar.extractall(donnees, filter="data")
    return racines


def lister(destination: Path) -> list[tuple[str, int, datetime]]:
    """Les sauvegardes présentes, la plus récente d'abord."""
    trouvees: list[tuple[str, int, datetime]] = []
    if not destination.exists():
        return trouvees
    for chemin in destination.glob("greffier-*.tar.gz"):
        quand = Nom.lire(chemin.name.removesuffix(".tar.gz"))
        if quand is None:
            continue
        trouvees.append((chemin.name, chemin.stat().st_size, quand))
    return sorted(trouvees, key=lambda ligne: ligne[2], reverse=True)


def place_disponible(destination: Path) -> int:
    """Octets libres là où l'on écrit. Zéro si on ne sait pas."""
    try:
        return shutil.disk_usage(destination).free
    except OSError:
        return 0
