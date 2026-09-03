#!/usr/bin/env bash
# Pose les crochets git du projet.
set -euo pipefail
DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# « core.hooksPath » plutôt qu'une copie dans .git/hooks : les crochets restent
# sous contrôle de version, donc partagés et améliorables comme le reste.
git -C "$DEPOT" config core.hooksPath outils/crochets
chmod +x "$DEPOT"/outils/crochets/pre-commit
echo "✅ crochets actifs (core.hooksPath = outils/crochets)"
