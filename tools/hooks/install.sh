#!/usr/bin/env bash
# Installs the project's git hooks.
set -euo pipefail
DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# `core.hooksPath` rather than a copy in .git/hooks: the hooks stay under
# version control, so they are shared and can be improved like the rest.
git -C "$DEPOT" config core.hooksPath tools/hooks
chmod +x "$DEPOT"/tools/hooks/pre-commit
echo "✅ crochets actifs (core.hooksPath = tools/hooks)"
