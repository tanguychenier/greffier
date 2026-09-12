"""The code that lives inside strings, which no checker reads.

Two failures shipped this way after a rename. `platform.recorder()` replaced
`platform.machine()` in the installer, which then died on its first printed
line; and the installer loaded the voiceprint model through
`python -c "... import ExtracteurTitaNet"`, a class that had become
`TitaNetExtractor`, so it declared the model broken on a machine where it
worked. mypy reads neither, the tests import neither, and the installer is the
first thing a new user runs.
"""

import ast
import importlib
import pathlib
import re

RACINE = pathlib.Path(__file__).resolve().parents[1]

#: The standard modules whose surface is worth checking. A rename that hits one
#: of them raises only when the line runs, which for a tool may be months later.
STANDARD = [
    "platform", "os", "sys", "shutil", "subprocess", "time", "json", "re",
    "pathlib", "socket", "ssl", "smtplib", "hashlib", "math", "textwrap",
    "unicodedata", "sqlite3", "datetime", "itertools", "functools", "collections",
    "threading", "contextlib", "pickle", "tarfile", "zipfile", "argparse",
    "tomllib", "base64", "getpass", "io", "random", "secrets", "signal", "stat",
    "string", "struct", "tempfile", "traceback", "uuid", "wave", "webbrowser",
    "difflib", "statistics",
]


def fichiers_python() -> list[pathlib.Path]:
    return [
        p for racine in ("src", "tools")
        for p in sorted((RACINE / racine).rglob("*.py"))
    ]


class TestTheStandardLibraryIsCalledByItsRealNames:
    def test_no_call_to_a_function_that_does_not_exist(self):
        charges = {}
        for nom in STANDARD:
            try:
                charges[nom] = importlib.import_module(nom)
            except ImportError:  # pragma: no cover, dépend du système
                continue

        fautes = []
        for p in fichiers_python():
            arbre = ast.parse(p.read_text(encoding="utf-8"))
            importes = {
                a.name for n in ast.walk(arbre) if isinstance(n, ast.Import)
                for a in n.names if a.asname is None and a.name in charges
            }
            for n in ast.walk(arbre):
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id in importes
                        and not hasattr(charges[n.value.id], n.attr)):
                    fautes.append(
                        f"{p.relative_to(RACINE)}:{n.lineno} "
                        f"{n.value.id}.{n.attr} n'existe pas"
                    )
        assert not fautes, "\n".join(fautes)


class TestTheCodeQuotedInsideStringsStillResolves:
    """`python -c "from greffier.x import Y"` is code that no checker reads."""

    MOTIF = re.compile(r"from (greffier[\w.]+) import ([A-Za-z_][\w]*)")

    def _citations(self):
        for p in fichiers_python():
            arbre = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(arbre):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    for module, nom in self.MOTIF.findall(n.value):
                        yield p, n.lineno, module, nom

    def test_every_quoted_import_names_something_that_exists(self):
        fautes = []
        for p, ligne, module, nom in self._citations():
            try:
                charge = importlib.import_module(module)
            except ImportError as trouble:
                fautes.append(f"{p.relative_to(RACINE)}:{ligne} {module} : {trouble}")
                continue
            if not hasattr(charge, nom):
                fautes.append(
                    f"{p.relative_to(RACINE)}:{ligne} {module}.{nom} n'existe pas"
                )
        assert not fautes, "\n".join(fautes)

    def test_the_check_actually_looks_at_something(self):
        """Guards against the check passing because it found nothing to read."""
        assert list(self._citations()), "aucun import cité : le contrôle ne prouve rien"
