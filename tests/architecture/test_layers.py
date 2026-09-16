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
PACKAGE = RACINE / "src" / "greffier"

#: What the domain has no right to know: neither the world, nor the layers that
#: touch it. `pathlib` is tolerated for typing a path; what is forbidden are the
#: libraries that READ the world.
FORBIDDEN_TO_THE_DOMAIN = frozenset({
    "subprocess", "socket", "urllib", "requests", "httpx", "smtplib",
    "pydantic", "pydantic_settings", "tkinter", "typer", "sherpa_onnx",
    "soundfile", "numpy", "faster_whisper", "tomllib",
})

#: The layers a module of a given layer is not allowed to import.
FORBIDDEN = {
    "domain": ("greffier.adapters", "greffier.application", "greffier.interface",
                "greffier.cli", "greffier.wiring", "greffier.locations"),
    "application": ("greffier.adapters", "greffier.interface", "greffier.cli",
                    "greffier.wiring"),
    "ports": ("greffier.adapters", "greffier.application", "greffier.interface",
              "greffier.cli", "greffier.wiring"),
}


def modules_of(layer: str) -> list[Path]:
    """The modules of a layer, and never an empty list.

    Renaming `domaine/` to `domain/` left these rules reading a folder that no
    longer existed, so they passed on nothing for as long as the rename lasted.
    A check that cannot find what it guards has to say so.
    """
    folder = PACKAGE / layer
    assert folder.is_dir(), f"la couche « {layer} » n'existe pas : {folder}"
    files = sorted(folder.rglob("*.py"))
    assert files, f"la couche « {layer} » est vide : rien à vérifier"
    return files


def imports_of(file: Path) -> list[str]:
    """Every module imported, late imports included.

    `ast.walk` goes down into function bodies: an import written in the middle of a
    method to avoid a cycle is a dependency like any other, and that is how they
    come back in quietly.
    """
    tree = ast.parse(file.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


class TestTheDomainIsPure:
    def test_it_imports_no_library_that_touches_the_world(self):
        faults = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("domain")
            for name in imports_of(file)
            if name.split(".")[0] in FORBIDDEN_TO_THE_DOMAIN
        ]
        assert not faults, "\n".join(faults)

    def test_it_knows_no_other_layer(self):
        faults = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("domain")
            for name in imports_of(file)
            if name.startswith(FORBIDDEN["domain"])
        ]
        assert not faults, "\n".join(faults)


class TestTheDependenciesPointInwards:
    def test_the_application_imports_no_adapter(self):
        """Late imports included: that is where they were hiding."""
        faults = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("application")
            for name in imports_of(file)
            if name.startswith(FORBIDDEN["application"])
        ]
        assert not faults, "\n".join(faults)

    def test_the_ports_know_only_the_domain(self):
        faults = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("ports")
            for name in imports_of(file)
            if name.startswith(FORBIDDEN["ports"])
        ]
        assert not faults, "\n".join(faults)


class TestTheRootOfThePackageStaysEmpty:
    """Six modules had settled there, outside every layer.

    What is allowed to live there: the primary command-line adapter, the entry
    point Python demands, the composition root, which is legitimately outside the
    layers since it wires them, and the locations, whose path is a contract with
    the installer, which loads them by literal path before anything is installed.
    """

    ALLOWED = frozenset({
        "__init__.py", "__main__.py", "cli.py", "wiring.py", "locations.py",
    })

    def test_nothing_new_settles_at_the_root(self):
        present_line = {f.name for f in PACKAGE.glob("*.py")}
        assert present_line <= self.ALLOWED, (
            f"hors couche : {sorted(present_line - self.ALLOWED)}"
        )


class TestThePrimaryAdaptersDoNotLeanOnEachOther:
    """The window and the command line are two doors, not a hierarchy.

    The window reached into the command line's private functions to start the
    live thread and the hardware watch. Starting a detached process is adapter
    work and belongs to neither door; where one door needs the other's private
    helpers, the thing they share is in the wrong place.
    """

    #: What is left of that coupling, named rather than tolerated silently: the
    #: macOS capture setup, some eighty lines that also carry their own output
    #: through typer. Moving it needs a machine this one is not.
    STAYS_KNOWN = frozenset({"_prepare_capture", "_restore_the_output"})

    def _imports_of_the_cli(self) -> set[str]:
        import ast

        window = PACKAGE / "interface" / "window.py"
        the_names: set[str] = set()
        for node in ast.walk(ast.parse(window.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.ImportFrom)
                    and node.module == "greffier.cli"):
                the_names |= {alias.name for alias in node.names}
        return the_names

    def test_the_window_borrows_nothing_new_from_the_command_line(self):
        borrowings = self._imports_of_the_cli()
        assert borrowings <= self.STAYS_KNOWN, (
            f"la fenêtre emprunte à la ligne de commande : "
            f"{sorted(borrowings - self.STAYS_KNOWN)}"
        )
