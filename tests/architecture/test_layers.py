"""L'architecture, vérifiée par la machine plutôt que par la relecture.

Le README annonce une architecture hexagonale : domaine pur au centre, ports
autour, application qui orchestre, adaptateurs en périphérie. Cette promesse
tenait par la vigilance, et la vigilance s'use — six modules avaient fini par
s'installer à la racine du paquet, hors de toute couche, et le README n'en
documentait qu'un.

Ces tests lisent les imports avec `ast`, y compris les imports tardifs écrits à
l'intérieur d'une fonction : c'est précisément là que se cachent les
dépendances qu'on ne veut pas avouer.
"""

from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
PAQUET = RACINE / "src" / "greffier"

#: Ce que le domaine n'a pas le droit de connaître : ni le monde, ni les couches
#: qui le touchent. `pathlib` est toléré pour typer un chemin ; ce sont les
#: bibliothèques qui LISENT le monde qui sont interdites.
INTERDIT_AU_DOMAINE = frozenset({
    "subprocess", "socket", "urllib", "requests", "httpx", "smtplib",
    "pydantic", "pydantic_settings", "tkinter", "typer", "sherpa_onnx",
    "soundfile", "numpy", "faster_whisper", "tomllib",
})

#: Les couches qu'un module d'une couche donnée n'a pas le droit d'importer.
INTERDITS = {
    "domain": ("greffier.adapters", "greffier.application", "greffier.interface",
                "greffier.cli", "greffier.wiring", "greffier.locations"),
    "application": ("greffier.adapters", "greffier.interface", "greffier.cli",
                    "greffier.wiring"),
    "ports": ("greffier.adapters", "greffier.application", "greffier.interface",
              "greffier.cli", "greffier.wiring"),
}


def modules_of(couche: str) -> list[Path]:
    """The modules of a layer, and never an empty list.

    Renaming `domaine/` to `domain/` left these rules reading a folder that no
    longer existed, so they passed on nothing for as long as the rename lasted.
    A check that cannot find what it guards has to say so.
    """
    dossier = PAQUET / couche
    assert dossier.is_dir(), f"la couche « {couche} » n'existe pas : {dossier}"
    fichiers = sorted(dossier.rglob("*.py"))
    assert fichiers, f"la couche « {couche} » est vide : rien à vérifier"
    return fichiers


def imports_of(file: Path) -> list[str]:
    """Tous les modules importés, imports tardifs compris.

    `ast.walk` descend dans les corps de fonction : un « import » écrit au
    milieu d'une méthode pour éviter un cycle est une dépendance comme une
    autre, et c'est la façon dont elles reviennent en douce.
    """
    arbre = ast.parse(file.read_text(encoding="utf-8"))
    names: list[str] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            names += [alias.name for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and noeud.level == 0:
            names.append(noeud.module)
    return names


class TestTheDomainIsPure:
    def test_it_imports_no_library_that_touches_the_world(self):
        fautes = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("domain")
            for name in imports_of(file)
            if name.split(".")[0] in INTERDIT_AU_DOMAINE
        ]
        assert not fautes, "\n".join(fautes)

    def test_it_knows_no_other_layer(self):
        fautes = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("domain")
            for name in imports_of(file)
            if name.startswith(INTERDITS["domain"])
        ]
        assert not fautes, "\n".join(fautes)


class TestTheDependenciesPointInwards:
    def test_the_application_imports_no_adapter(self):
        """Y compris les imports tardifs : c'est là qu'ils se cachaient."""
        fautes = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("application")
            for name in imports_of(file)
            if name.startswith(INTERDITS["application"])
        ]
        assert not fautes, "\n".join(fautes)

    def test_the_ports_know_only_the_domain(self):
        fautes = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("ports")
            for name in imports_of(file)
            if name.startswith(INTERDITS["ports"])
        ]
        assert not fautes, "\n".join(fautes)


class TestTheRootOfThePackageStaysEmpty:
    """Six modules s'y étaient installés hors de toute couche.

    Ce qui a le droit d'y vivre : l'adaptateur primaire en ligne de commande, le
    point d'entrée que Python impose, la racine de composition — qui est
    légitimement hors des couches puisqu'elle les câble — et les emplacements,
    dont le chemin est un contrat avec l'installeur, qui les charge par chemin
    littéral avant toute installation.
    """

    AUTORISES = frozenset({
        "__init__.py", "__main__.py", "cli.py", "wiring.py", "locations.py",
    })

    def test_nothing_new_settles_at_the_root(self):
        present_line = {f.name for f in PAQUET.glob("*.py")}
        assert present_line <= self.AUTORISES, (
            f"hors couche : {sorted(present_line - self.AUTORISES)}"
        )
