"""The architecture, checked by the machine rather than by reading.

The README announces a hexagonal architecture: a pure domain at the centre,
ports around it, an application that orchestrates, adapters at the edge. That
promise held by vigilance, and vigilance wears out. Six modules had ended up
settling at the root of the package, outside every layer, and the README
documented only one of them.

These tests read the imports with `ast`, late imports written inside a function
included: that is precisely where the dependencies one would rather not admit
are hidden. Relative imports are resolved against the file's package, so that
`from ..adapters import x` reads as `greffier.adapters.x`; they used to be
skipped, which left a door open that nothing had walked through yet.

What is still NOT checked, and why: the window and the command line import
adapters directly, 56 imports under `interface/` and 29 in `cli.py` on
2026-10-03, counted with `imports_of` below, which reads `from
greffier.adapters import a, b` as two. Both are primary adapters and may
know the outside, but the composition root exists so that they do not have to:
every one of those imports bypasses `wiring`. Closing that is a refactoring of
the two doors, not a rule to add here, and a rule written today would only be
an allow-list of eighty-five lines.
"""

from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
SOURCES = RACINE / "src"
PACKAGE = SOURCES / "greffier"

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
    "adapters": ("greffier.application", "greffier.interface", "greffier.cli",
                 "greffier.wiring"),
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


def imports_of(file: Path, root: Path = SOURCES) -> list[str]:
    """Every module imported, late and relative imports included.

    `ast.walk` goes down into function bodies: an import written in the middle of a
    method to avoid a cycle is a dependency like any other, and that is how they
    come back in quietly. `root` is the folder the top-level package sits in; it
    is what a relative import is resolved against.
    """
    tree = ast.parse(file.read_text(encoding="utf-8"))
    package = package_of(file, root)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names += _modules_named_by(node, package, root)
    return names


def package_of(file: Path, root: Path) -> list[str]:
    """The dotted package a file belongs to, as `from . import x` reads it.

    An `__init__.py` belongs to its own folder, like every other file in it.
    """
    return list(file.relative_to(root).parent.parts)


def _modules_named_by(node: ast.ImportFrom, package: list[str], root: Path) -> list[str]:
    """The modules one `from … import …` reaches.

    A dot per level climbs the package: one dot is the package itself, two its
    parent. When what is named is a package rather than a module, the names
    are the modules, `from .. import adapters` and `from greffier import
    adapters` show their dependency nowhere else; a plain attribute imported
    from a package reads as a module too, which the layer rules, prefix
    matches, do not mind.
    """
    base = package[: len(package) - node.level + 1] if node.level else []
    origin = ".".join([*base, node.module] if node.module else base)
    if not (root / Path(*origin.split("."))).is_dir():
        return [origin]
    return [f"{origin}.{alias.name}" for alias in node.names]


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

    def test_the_adapters_know_neither_the_application_nor_the_doors(self):
        """An adapter is called; it calls nothing above it.

        The layer had no rule until 2026-10-03, by omission rather than choice.
        The forty-six modules read clean that day, so the rule carries no
        allow-list: the first violation will be one to fix, not to record.
        """
        faults = [
            f"{file.relative_to(RACINE)} importe {name}"
            for file in modules_of("adapters")
            for name in imports_of(file)
            if name.startswith(FORBIDDEN["adapters"])
        ]
        assert not faults, "\n".join(faults)


class TestTheReaderSeesRelativeImports:
    """`from ..adapters import x` used to be invisible.

    The reader kept only the imports with no leading dot, so an application
    module written that way would have passed every rule above. Nothing in
    the package is written that way today; the rule has to hold before it is.
    """

    LAYOUT = ("pkg/__init__.py", "pkg/adapters/__init__.py", "pkg/adapters/ffmpeg.py",
              "pkg/application/__init__.py", "pkg/domain/__init__.py",
              "pkg/domain/models.py")

    def _module(self, tmp_path: Path, path: str, source: str) -> Path:
        for name in self.LAYOUT:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).touch()
        module = tmp_path / path
        module.write_text(source, encoding="utf-8")
        return module

    def test_a_relative_import_is_resolved_against_the_file_s_package(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/thing.py",
                              "from ..adapters import ffmpeg\n")
        assert imports_of(module, root=tmp_path) == ["pkg.adapters.ffmpeg"]

    def test_one_dot_is_the_package_itself(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/thing.py",
                              "from .sibling import helper\nfrom . import other\n")
        assert imports_of(module, root=tmp_path) == [
            "pkg.application.sibling", "pkg.application.other",
        ]

    def test_a_late_relative_import_inside_a_function_is_seen_too(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/thing.py",
                              "def run():\n    from ..adapters import ffmpeg\n")
        assert imports_of(module, root=tmp_path) == ["pkg.adapters.ffmpeg"]

    def test_an_init_file_belongs_to_its_own_folder(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/__init__.py",
                              "from .thing import run\n")
        assert imports_of(module, root=tmp_path) == ["pkg.application.thing"]

    def test_a_name_imported_from_a_package_is_read_as_one_of_its_modules(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/thing.py",
                              "from pkg import adapters\n")
        assert imports_of(module, root=tmp_path) == ["pkg.adapters"]

    def test_a_name_imported_from_a_module_adds_nothing_to_it(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/thing.py",
                              "from pkg.domain.models import Span\n")
        assert imports_of(module, root=tmp_path) == ["pkg.domain.models"]

    def test_the_layer_rule_now_catches_the_relative_form(self, tmp_path):
        module = self._module(tmp_path, "pkg/application/thing.py",
                              "from ..adapters import ffmpeg\n")
        forbidden = tuple(f"pkg.{layer}" for layer in ("adapters", "interface"))
        faults = [n for n in imports_of(module, root=tmp_path) if n.startswith(forbidden)]
        assert faults == ["pkg.adapters.ffmpeg"]


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
