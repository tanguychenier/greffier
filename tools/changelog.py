#!/usr/bin/env python3
"""Generates CHANGELOG.md from the git history.

The messages follow the Angular convention, `type(scope): subject`, which is
exactly what makes it possible to produce this file without keeping it by hand,
and so without it going stale.

    python3 tools/changelog.py > CHANGELOG.md
"""

import re
import subprocess
import sys
from collections import defaultdict

# Only the types a reader cares about. A `style` or a `chore` changes nothing
# for whoever uses the tool.
TITLES = {
    "feat": "New",
    "fix": "Fixed",
    "perf": "Performance",
    "docs": "Documentation",
    "refactor": "Refactored",
}
PATTERN = re.compile(
    r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaks>!)?: (?P<subject>.+)$")


def commits() -> list[tuple[str, str]]:
    output = subprocess.run(
        ["git", "log", "--no-merges", "--pretty=format:%h\t%s"],
        capture_output=True, text=True, check=True,
    ).stdout
    pairs = []
    for line in output.splitlines():
        if "\t" in line:
            short_hash, subject = line.split("\t", 1)
            pairs.append((short_hash, subject))
    return pairs


def main() -> int:
    by_type: dict[str, list[str]] = defaultdict(list)
    breaks: list[str] = []
    for short_hash, subject in commits():
        found = PATTERN.match(subject)
        if not found:
            continue
        scope = found.group("scope")
        prefix = f"**{scope}** : " if scope else ""
        line = f"- {prefix}{found.group('subject')} (`{short_hash}`)"
        if found.group("breaks"):
            breaks.append(line)
        by_type[found.group("type")].append(line)

    print("# Changelog\n")
    print("Generated from the commit messages, which follow the Angular"
          " convention:\n")
    print("    python3 tools/changelog.py > CHANGELOG.md\n")
    if breaks:
        print("## Breaking changes\n")
        print("\n".join(breaks) + "\n")
    for type_, title in TITLES.items():
        if by_type.get(type_):
            print(f"## {title}\n")
            print("\n".join(by_type[type_]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
