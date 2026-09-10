#!/usr/bin/env python3
"""Engendre CHANGELOG.md depuis l'historique git.

Les messages suivent la convention Angular : « type(portée): sujet ». C'est
précisément ce qui permet de produire ce fichier sans le tenir à la main — et
donc sans qu'il finisse périmé.

    python3 tools/changelog.py > CHANGELOG.md
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
    output = subprocess.run(
        ["git", "log", "--no-merges", "--pretty=format:%h\t%s"],
        capture_output=True, text=True, check=True,
    ).stdout
    couples = []
    for line in output.splitlines():
        if "\t" in line:
            voiceprint, subject = line.split("\t", 1)
            couples.append((voiceprint, subject))
    return couples


def main() -> int:
    par_type: dict[str, list[str]] = defaultdict(list)
    ruptures: list[str] = []
    for voiceprint, subject in commits():
        trouve = MOTIF.match(subject)
        if not trouve:
            continue
        portee = trouve.group("portee")
        prefixe = f"**{portee}** — " if portee else ""
        line = f"- {prefixe}{trouve.group('sujet')} (`{voiceprint}`)"
        if trouve.group("casse"):
            ruptures.append(line)
        par_type[trouve.group("type")].append(line)

    print("# Journal des modifications\n")
    print("Engendré depuis les messages de commit (convention Angular) :\n")
    print("    python3 tools/changelog.py > CHANGELOG.md\n")
    if ruptures:
        print("## Ruptures de compatibilité\n")
        print("\n".join(ruptures) + "\n")
    for type_, title in TITRES.items():
        if par_type.get(type_):
            print(f"## {title}\n")
            print("\n".join(par_type[type_]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
