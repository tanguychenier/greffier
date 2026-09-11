"""The architecture, checked by the machine rather than by reading.

The README announces a hexagonal architecture: a pure domain at the centre,
ports around it, an application that orchestrates, adapters at the edge. That
promise held by vigilance, and vigilance wears out. Six modules had ended up
settling at the root of the package, outside every layer, and the README
documented only one of them.

These tests read the imports with `ast`, late imports written inside a function
included: that is precisely where the dependencies one would rather not admit
are hidden.
"""

from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
PAQUET = RACINE / "src" / "greffier"

#: What the domain has no right to know: neither the world, nor the layers that
#: touch it. `pathlib` is tolerated for typing a path; what is forbidden are the
#: libraries that READ the world.
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
    """Every module imported, late imports included.

    `ast.walk` goes down into function bodies: an import written in the middle of a
    method to avoid a cycle is a dependency like any other, and that is how they
    come back in quietly.
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
        """Late imports included: that is where they were hiding."""
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
    """Six modules had settled there, outside every layer.

    What is allowed to live there: the primary command-line adapter, the entry
    point Python demands, the composition root, which is legitimately outside the
    layers since it wires them, and the locations, whose path is a contract with
    the installer, which loads them by literal path before anything is installed.
    """

    AUTORISES = frozenset({
        "__init__.py", "__main__.py", "cli.py", "wiring.py", "locations.py",
    })

    def test_nothing_new_settles_at_the_root(self):
        present_line = {f.name for f in PAQUET.glob("*.py")}
        assert present_line <= self.AUTORISES, (
            f"hors couche : {sorted(present_line - self.AUTORISES)}"
        )
