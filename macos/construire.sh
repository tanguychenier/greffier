#!/usr/bin/env bash
# Fabrique /Applications/Greffier.app : une application autonome qu'on double-clique.
#
# Autonome, c'est le point. L'interpréteur, sa bibliothèque standard, les
# paquets et le code de Greffier sont **copiés dans le paquet** : rien ne pointe
# vers le dépôt ni vers un dossier caché du compte. Les versions précédentes —
# un lien `Contents/lib` vers `~/.local/share/uv/…` et un PYTHONPATH vers le
# `.venv` du dépôt — faisaient lire ces dossiers à chaque lancement et par
# chaque processus auxiliaire (veille, direct) ; le garde du poste (WithSecure
# XFENCE) contestait chacun de ces accès, jusqu'à refuser une écriture en pleine
# réunion. Un logiciel installé n'a pas à dépendre de l'endroit d'où on l'a
# construit.
#
# Contents/MacOS/Greffier est une copie de l'interpréteur, pas un script qui
# l'appelle : macOS attribue le nom du Dock et de la barre de menus à
# l'exécutable réellement lancé, pas à `argv[0]` — mesuré, `exec -a` n'y change
# rien. L'interpréteur retrouve sa bibliothèque par `@executable_path/../lib`,
# d'où `Contents/lib`, copie de celle de l'installation d'origine, dans laquelle
# uv installe ensuite Greffier et ses dépendances. Lancé sans argument par
# LaunchServices, l'interpréteur importe `sitecustomize` depuis ses propres
# paquets : c'est lui qui ouvre la fenêtre (voir `lanceur_sitecustomize.py`).
#
# Le paquet est signé avec une identité **stable** (`identite-de-signature.sh`),
# pas ad hoc. Une signature ad hoc n'est que le hachage du binaire : chaque
# reconstruction en faisait une application inconnue pour macOS — micro et
# Outlook redemandés — comme pour XFENCE. Avec un certificat, l'identité tient
# au certificat : les autorisations données une fois survivent.
#
# Conséquence assumée : une modification du code ne se voit dans l'application
# qu'après reconstruction (outils/installer.py, ou ce script). C'est le
# comportement d'un logiciel installé ; la ligne de commande du dépôt
# (`.venv/bin/greffier`) reste là pour développer, elle suit le code.
#
# Appelé par outils/installer.py ; relançable à la main.
set -euo pipefail

DEPOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IDENTIFIANT="fr.centralesupelec.greffier"

# /Applications et non ~/Applications : ce dernier n'est pas indexé par
# Spotlight ni parcouru par le Launchpad, donc l'application y est installée
# sans qu'aucune icône n'apparaisse nulle part. Constaté : « je n'ai aucune
# icône pour la lancer ». Le dossier est inscriptible par le groupe admin, donc
# sans mot de passe dans le cas courant ; on se rabat sur le dossier personnel
# s'il ne l'est pas.
if [ -n "${1:-}" ]; then
  APP="$1"
elif [ -w /Applications ]; then
  APP="/Applications/Greffier.app"
else
  APP="$HOME/Applications/Greffier.app"
fi

# L'interpréteur du dépôt. Il doit être relogeable — c'est le cas de ceux
# qu'installe uv (python-build-standalone) : libpython et la bibliothèque
# standard dans `lib/`, retrouvées par `@executable_path/../lib`. Un Python
# Homebrew ou système est un « framework », qui ne se copie pas ainsi.
PYTHON="$DEPOT/.venv/bin/python3"
[ -x "$PYTHON" ] || { echo "❌ Pas d'environnement dans $DEPOT/.venv : lance outils/installer.py." >&2; exit 1; }
VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
BASE_PREFIX="$("$PYTHON" -c 'import sys; print(sys.base_prefix)')"
if [ ! -f "$BASE_PREFIX/lib/libpython$VERSION.dylib" ] || [ ! -x "$BASE_PREFIX/bin/python$VERSION" ]; then
  echo "❌ L'interpréteur de $BASE_PREFIX n'est pas relogeable." >&2
  echo "   Il faut un Python installé par uv : rm -rf .venv && uv venv --python 3.13, puis relance l'installeur." >&2
  exit 1
fi
command -v uv >/dev/null 2>&1 || { echo "❌ uv est nécessaire pour remplir le paquet : brew install uv" >&2; exit 1; }

# Ni le dossier utilisateur de Python (~/.local/lib/python…, caché), ni de .pyc
# écrit pendant la construction ailleurs que là où on le demande.
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

# macOS lance le paquet avec un PATH minimal (/usr/bin:/bin:…), pas celui du
# shell : ffmpeg (Homebrew) et claude (compte rendu) y sont introuvables même
# installés, en échec silencieux jusqu'au clic qui en a besoin — constaté à
# l'usage. Le PATH d'un vrai shell de connexion, mesuré sur cette machine,
# corrige ça sans rien deviner. Posé dans `sitecustomize`, pas dans
# `LSEnvironment` : mesuré, ce dernier pose bien les variables PYTHON* mais pas
# PATH, que macOS semble réimposer par-dessus après coup.
CHEMIN="$("${SHELL:-/bin/zsh}" -lic 'printf "GREFFIER_PATH=%s\n" "$PATH"' 2>/dev/null \
  | sed -n 's/^GREFFIER_PATH=//p' | tail -1)"
[ -n "$CHEMIN" ] || CHEMIN="$PATH"

# ~/.local/bin d'abord, avant Homebrew. Ce n'est pas une préférence : c'est la
# stabilité du chemin. Le garde du poste (WithSecure XFENCE) retient le chemin
# du programme tel qu'il le voit, sans résoudre les liens symboliques — mesuré
# dans son fichier de règles. Un outil installé par Homebrew vit sous
# /opt/homebrew/Caskroom/<outil>/<version>/, chemin qui change à chaque mise à
# jour : la règle accordée meurt avec l'ancienne version, et le dialogue revient
# — en pleine réunion pour `claude`, qui rédige le compte rendu. Le même outil
# sous ~/.local/bin est un lien de nom fixe : la règle survit aux mises à jour.
# Constaté le 2026-09-02 : le paquet rédigeait avec le Claude Code 2.1.195 du
# Caskroom alors que le 2.1.258 était installé sous ~/.local/bin.
CHEMIN="$HOME/.local/bin:$CHEMIN"

# Construit à côté, puis remplace d'un coup : une construction qui échoue ne
# laisse pas une application à moitié faite dans /Applications.
ATELIER="$(mktemp -d "${TMPDIR:-/tmp}/greffier-paquet.XXXXXX")"
trap 'rm -rf "$ATELIER"' EXIT
PAQUET="$ATELIER/Greffier.app"
CONTENU="$PAQUET/Contents"
EXECUTABLE="$CONTENU/MacOS/Greffier"
SITE="$CONTENU/lib/python$VERSION/site-packages"
mkdir -p "$CONTENU/MacOS" "$CONTENU/Resources"
[ -f "$DEPOT/macos/Greffier.icns" ] && cp "$DEPOT/macos/Greffier.icns" "$CONTENU/Resources/"

echo "→ interpréteur et bibliothèque standard"
cp "$BASE_PREFIX/bin/python$VERSION" "$EXECUTABLE"
chmod 755 "$EXECUTABLE"
cp -R "$BASE_PREFIX/lib" "$CONTENU/lib"
# Notre copie n'est plus l'installation gérée par uv : le marqueur qui interdit
# d'y installer quoi que ce soit n'a plus lieu d'être — sans quoi uv refuse.
rm -f "$CONTENU/lib/python$VERSION/EXTERNALLY-MANAGED"
# pip n'a rien à faire dans une application : c'est uv qui remplit le paquet.
rm -rf "$SITE"/pip "$SITE"/pip-*.dist-info

echo "→ Greffier et ses dépendances"
# Installation ordinaire, pas éditable : le code est copié dans le paquet.
uv pip install --quiet --python "$EXECUTABLE" "$DEPOT"

# Le lanceur du double-clic, avec le PATH mesuré, parmi les paquets : `site`
# l'importe de lui-même au démarrage de l'interpréteur.
CHEMIN="$CHEMIN" "$EXECUTABLE" -c "
import json, os
gabarit = open('$DEPOT/macos/lanceur_sitecustomize.py', encoding='utf-8').read()
gabarit = gabarit.replace('__CHEMIN__', json.dumps(os.environ['CHEMIN']))
open('$SITE/sitecustomize.py', 'w', encoding='utf-8').write(gabarit)
"

# Tout doit s'importer depuis le paquet seul, avant de toucher à /Applications.
"$EXECUTABLE" -c 'import greffier.cli, numpy, sherpa_onnx, soundfile, tkinter' \
  || { echo "❌ Le paquet ne s'importe pas : rien n'a été installé." >&2; exit 1; }

# Le code compilé à l'avance, et l'interpréteur prié de ne plus rien écrire
# (PYTHONDONTWRITEBYTECODE dans Info.plist) : un .pyc écrit après coup dans le
# paquet en romprait le sceau.
echo "→ précompilation"
"$EXECUTABLE" -m compileall -q -j 0 "$CONTENU/lib/python$VERSION" >/dev/null 2>&1 || true

# Le relevé du matériel exécute un petit binaire Swift toutes les quelques
# secondes. Compilé dans le paquet — donc signé et couvert avec lui — plutôt
# que dans ~/.local : XFENCE contestait chaque exécution depuis ~/.local, une
# demande toutes les cinq secondes en réunion.
if command -v swiftc >/dev/null 2>&1; then
  echo "→ listeur de périphériques"
  swiftc -O "$DEPOT/macos/creer-peripheriques.swift" \
    -o "$CONTENU/Resources/lister-peripheriques" 2>/dev/null \
    || echo "⚠️  Listeur non compilé (repli sur le cache, avec des dialogues en plus)."
fi

cat > "$CONTENU/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Greffier</string>
  <key>CFBundleDisplayName</key>       <string>Greffier</string>
  <key>CFBundleIdentifier</key>        <string>$IDENTIFIANT</string>
  <key>CFBundleExecutable</key>        <string>Greffier</string>
  <key>CFBundleIconFile</key>          <string>Greffier</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.3.0</string>
  <key>LSMinimumSystemVersion</key>    <string>13.0</string>
  <key>NSHighResolutionCapable</key>   <true/>
  <!-- Jamais de terminaison silencieuse par le système : la fenêtre porte la
       capture, et macOS qui la réclame en pleine réunion coupe l'audio net.
       Le journal système a montré l'app marquée terminable au lancement
       (_kLSApplicationWouldBeTerminatedByTALKey), autant fermer la porte. -->
  <key>NSSupportsAutomaticTermination</key> <false/>
  <key>NSSupportsSuddenTermination</key>    <false/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Greffier affiche le niveau de ton micro et enregistre la réunion pour la transcrire sur ce Mac.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>Greffier pilote Outlook pour t'envoyer le compte rendu par courriel.</string>
  <!-- Pas de PYTHONPATH : tout est dans le paquet. Les deux réglages empêchent
       l'interpréteur d'en sortir ou d'y écrire : sans PYTHONNOUSERSITE il irait
       lire ~/.local/lib/python…, un dossier caché, précisément ce qu'on ne veut
       plus toucher ; sans PYTHONDONTWRITEBYTECODE il écrirait des .pyc dans le
       paquet et en romprait le sceau. -->
  <key>LSEnvironment</key>
  <dict>
    <key>PYTHONNOUSERSITE</key>        <string>1</string>
    <key>PYTHONDONTWRITEBYTECODE</key> <string>1</string>
  </dict>
</dict>
</plist>
PLIST
printf 'APPL????' > "$CONTENU/PkgInfo"

echo "→ signature"
IDENTITE="$("$DEPOT/macos/identite-de-signature.sh")"
signer() { codesign --force --sign "$IDENTITE" --timestamp=none "$@"; }
# Les bibliothèques natives une à une d'abord, puis le paquet — qui signe
# l'exécutable principal et scelle le reste. Sans horodatage : il demande le
# réseau, et n'apporte rien à une application qui ne quitte pas le poste.
# « replacing existing signature » : les roues PyPI arrivent déjà signées ad
# hoc, codesign le dit pour chacune — des dizaines de lignes sans information.
# Filtré ; les vraies erreurs passent.
sans_bruit() { grep -v "replacing existing signature" >&2 || true; }
find "$CONTENU/lib" -type f \( -name '*.so' -o -name '*.dylib' \) -print0 \
  | xargs -0 codesign --force --sign "$IDENTITE" --timestamp=none 2> >(sans_bruit)
[ -x "$CONTENU/Resources/lister-peripheriques" ] \
  && signer --identifier "$IDENTIFIANT.lister-peripheriques" "$CONTENU/Resources/lister-peripheriques" 2> >(sans_bruit)
signer --identifier "$IDENTIFIANT" "$PAQUET" 2> >(sans_bruit)
codesign --verify --strict --deep "$PAQUET" 2>/dev/null \
  || echo "⚠️  La vérification de la signature a échoué : l'application fonctionnera, les autorisations peut-être pas."

# Remplacement d'un coup. Même volume dans le cas courant : un simple renommage.
rm -rf "$APP"
mv "$PAQUET" "$APP"

# Sans cet enregistrement, l'application existe sur le disque mais n'apparaît ni
# dans le Launchpad, ni dans Spotlight, ni avec son icône dans le Finder.
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$APP" 2>/dev/null
touch "$APP"

# Un ancien exemplaire dans le dossier personnel donnerait deux icônes pour la
# même application, dont une périmée.
ANCIEN="$HOME/Applications/Greffier.app"
[ "$APP" != "$ANCIEN" ] && [ -d "$ANCIEN" ] && rm -rf "$ANCIEN" \
  && echo "   ancien exemplaire retiré de ~/Applications"

echo "✅ $APP ($(du -sh "$APP" | cut -f1), autonome)"
if [ "$IDENTITE" = "-" ]; then
  echo "   signature ad hoc : les autorisations seront redemandées à chaque reconstruction"
else
  echo "   signé « $IDENTITE » : les autorisations survivent aux reconstructions"
fi
echo "   double-clic, ou cherche « Greffier » dans le Launchpad"
echo "   journal : ~/Library/Logs/Greffier.log"
