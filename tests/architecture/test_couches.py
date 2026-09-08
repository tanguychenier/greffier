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
    "domaine": ("greffier.adaptateurs", "greffier.application", "greffier.interface",
                "greffier.cli", "greffier.composition", "greffier.emplacements"),
    "application": ("greffier.adaptateurs", "greffier.interface", "greffier.cli",
                    "greffier.composition"),
    "ports": ("greffier.adaptateurs", "greffier.application", "greffier.interface",
              "greffier.cli", "greffier.composition"),
}


def modules_de(couche: str) -> list[Path]:
    return sorted((PAQUET / couche).rglob("*.py"))


def imports_de(fichier: Path) -> list[str]:
    """Tous les modules importés, imports tardifs compris.

    `ast.walk` descend dans les corps de fonction : un « import » écrit au
    milieu d'une méthode pour éviter un cycle est une dépendance comme une
    autre, et c'est la façon dont elles reviennent en douce.
    """
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    noms: list[str] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            noms += [alias.name for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module and noeud.level == 0:
            noms.append(noeud.module)
    return noms


class TestLeDomaineEstPur:
    def test_il_n_importe_aucune_bibliotheque_qui_touche_le_monde(self):
        fautes = [
            f"{fichier.relative_to(RACINE)} importe {nom}"
            for fichier in modules_de("domaine")
            for nom in imports_de(fichier)
            if nom.split(".")[0] in INTERDIT_AU_DOMAINE
        ]
        assert not fautes, "\n".join(fautes)

    def test_il_ne_connait_aucune_autre_couche(self):
        fautes = [
            f"{fichier.relative_to(RACINE)} importe {nom}"
            for fichier in modules_de("domaine")
            for nom in imports_de(fichier)
            if nom.startswith(INTERDITS["domaine"])
        ]
        assert not fautes, "\n".join(fautes)


class TestLesDependancesVontDansLeBonSens:
    def test_l_application_n_importe_aucun_adaptateur(self):
        """Y compris les imports tardifs : c'est là qu'ils se cachaient."""
        fautes = [
            f"{fichier.relative_to(RACINE)} importe {nom}"
            for fichier in modules_de("application")
            for nom in imports_de(fichier)
            if nom.startswith(INTERDITS["application"])
        ]
        assert not fautes, "\n".join(fautes)

    def test_les_ports_ne_connaissent_que_le_domaine(self):
        fautes = [
            f"{fichier.relative_to(RACINE)} importe {nom}"
            for fichier in modules_de("ports")
            for nom in imports_de(fichier)
            if nom.startswith(INTERDITS["ports"])
        ]
        assert not fautes, "\n".join(fautes)


class TestLaRacineDuPaquetResteVide:
    """Six modules s'y étaient installés hors de toute couche.

    Ce qui a le droit d'y vivre : l'adaptateur primaire en ligne de commande, le
    point d'entrée que Python impose, la racine de composition — qui est
    légitimement hors des couches puisqu'elle les câble — et les emplacements,
    dont le chemin est un contrat avec l'installeur, qui les charge par chemin
    littéral avant toute installation.
    """

    AUTORISES = frozenset({
        "__init__.py", "__main__.py", "cli.py", "composition.py", "emplacements.py",
    })

    def test_rien_de_nouveau_ne_s_installe_a_la_racine(self):
        presents = {f.name for f in PAQUET.glob("*.py")}
        assert presents <= self.AUTORISES, (
            f"hors couche : {sorted(presents - self.AUTORISES)}"
        )
