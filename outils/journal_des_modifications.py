#!/usr/bin/env python3
"""Engendre CHANGELOG.md depuis l'historique git.

Les messages suivent la convention Angular : « type(portée): sujet ». C'est
précisément ce qui permet de produire ce fichier sans le tenir à la main — et
donc sans qu'il finisse périmé.

    python3 outils/journal_des_modifications.py > CHANGELOG.md
"""

import re
import subprocess
import sys
from collections import defaultdict

# Seuls les types qui intéressent un lecteur. Un « style » ou un « chore » ne
# change rien pour qui utilise l'outil.
TITRES = {
    "feat": "Nouveautés",
    "fix": "Corrections",
    "perf": "Performance",
    "docs": "Documentation",
    "refactor": "Remaniements",
}
MOTIF = re.compile(r"^(?P<type>\w+)(?:\((?P<portee>[^)]+)\))?(?P<casse>!)?: (?P<sujet>.+)$")


def commits() -> list[tuple[str, str]]:
    sortie = subprocess.run(
        ["git", "log", "--no-merges", "--pretty=format:%h\t%s"],
        capture_output=True, text=True, check=True,
    ).stdout
    couples = []
    for ligne in sortie.splitlines():
        if "\t" in ligne:
            empreinte, sujet = ligne.split("\t", 1)
            couples.append((empreinte, sujet))
    return couples


def main() -> int:
    par_type: dict[str, list[str]] = defaultdict(list)
    ruptures: list[str] = []
    for empreinte, sujet in commits():
        trouve = MOTIF.match(sujet)
        if not trouve:
            continue
        portee = trouve.group("portee")
        prefixe = f"**{portee}** — " if portee else ""
        ligne = f"- {prefixe}{trouve.group('sujet')} (`{empreinte}`)"
        if trouve.group("casse"):
            ruptures.append(ligne)
        par_type[trouve.group("type")].append(ligne)

    print("# Journal des modifications\n")
    print("Engendré depuis les messages de commit (convention Angular) :\n")
    print("    python3 outils/journal_des_modifications.py > CHANGELOG.md\n")
    if ruptures:
        print("## Ruptures de compatibilité\n")
        print("\n".join(ruptures) + "\n")
    for type_, titre in TITRES.items():
        if par_type.get(type_):
            print(f"## {titre}\n")
            print("\n".join(par_type[type_]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
