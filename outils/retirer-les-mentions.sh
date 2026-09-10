#!/usr/bin/env bash
# Retire toute mention de Claude des messages de commit, puis republie.
#
# Un trailer « Co-Authored-By » fait apparaître un contributeur de plus sur la
# page GitHub du dépôt. Quatre-vingts commits en portent un, et il n'y a pas
# d'autre façon de les retirer que de réécrire les messages : un message de
# commit fait partie de ce qui est haché.
#
# À lancer depuis le dépôt. Réécrit l'historique local, puis pousse en force
# sur GitHub — d'où la confirmation, et la sauvegarde faite avant toute chose.

set -euo pipefail

DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEPOT"

SAUVEGARDE="$HOME/Documents/greffier-avant-retrait-des-mentions-$(date +%Y-%m-%d-%H%M).bundle"

echo "Dépôt        : $DEPOT"
echo "Sauvegarde   : $SAUVEGARDE"
printf 'Commits visés : '
git log --all --format='%H' | while read -r h; do
  git log -1 --format='%B' "$h" \
    | grep -qiE 'co-authored-by:.*claude|generated with .*claude' && echo "$h"
done | wc -l

command -v git-filter-repo >/dev/null 2>&1 || {
  echo "❌ git-filter-repo est nécessaire : brew install git-filter-repo" >&2
  exit 1
}

echo
echo "Ce script va RÉÉCRIRE l'historique et POUSSER EN FORCE sur main."
printf 'Taper « oui » pour continuer : '
read -r reponse
[ "$reponse" = "oui" ] || { echo "Rien n'a été fait."; exit 0; }

git bundle create "$SAUVEGARDE" --all >/dev/null
echo "✓ sauvegarde écrite"

# --force parce que filter-repo refuse un dépôt qui n'est pas fraîchement cloné.
# Les étiquettes suivent : elles pointent sur des commits réécrits.
git filter-repo --force --message-callback '
import re
gardees = [
    l for l in message.decode("utf-8", "replace").splitlines()
    if not re.match(r"^\s*co-authored-by:\s*claude", l, re.I)
    and not re.search(r"generated with .*claude", l, re.I)
]
while gardees and not gardees[-1].strip():
    gardees.pop()
return ("\n".join(gardees) + "\n").encode("utf-8")
'

echo "✓ historique réécrit"
printf 'Commits portant encore une mention : '
git log --all --format='%H' | while read -r h; do
  git log -1 --format='%B' "$h" \
    | grep -qiE 'co-authored-by:.*claude|generated with .*claude' && echo "$h"
done | wc -l

# filter-repo retire les dépôts distants pour éviter une republication
# involontaire : on le remet, puis on pousse tout.
git remote get-url github >/dev/null 2>&1 \
  || git remote add github https://github.com/tanguychenier/greffier.git
git push --force github main
git push --force --tags github
echo "✓ poussé. La liste des contributeurs se recalcule côté GitHub en quelques minutes."
