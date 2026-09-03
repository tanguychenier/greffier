#!/usr/bin/env bash
# Choisit avec quoi signer le paquet, et fabrique une identité s'il n'en existe
# aucune. Écrit le nom de l'identité sur la sortie standard ; « - » veut dire
# ad hoc. Tout le reste part sur la sortie d'erreur.
#
# Pourquoi une identité, et pas la signature ad hoc (`codesign --sign -`) :
# une signature ad hoc n'est que le hachage du binaire. À chaque reconstruction
# du paquet, macOS voyait donc une application inconnue et redemandait le micro
# et l'automatisation d'Outlook ; le garde du poste (XFENCE) aussi. Avec un
# certificat, l'exigence de code (« designated requirement ») repose sur le
# certificat et l'identifiant du paquet : les autorisations données une fois
# survivent aux reconstructions, et même au renouvellement du certificat, qui
# garde le même nom.
#
# Ordre de préférence :
#   1. GREFFIER_SIGNATURE, si posée (nom d'identité, ou « - » pour ad hoc) ;
#   2. un certificat Apple déjà dans le trousseau — Developer ID, sinon
#      Apple Development : ils ont une chaîne complète, rien à configurer ;
#   3. un certificat local « Greffier signature locale », créé ici une fois pour
#      toutes. macOS demande alors le mot de passe de session pour lui faire
#      confiance : c'est la seule fois où l'installation en demande un pour la
#      signature, et il n'y en aura plus ensuite. Mesuré : sans cette confiance
#      explicite, codesign ne voit même pas l'identité importée.
#   4. ad hoc, en dernier recours — avec les redemandes qui vont avec.
set -euo pipefail

NOM_LOCAL="Greffier signature locale"

if [ -n "${GREFFIER_SIGNATURE:-}" ]; then
  echo "$GREFFIER_SIGNATURE"
  exit 0
fi

identite_existante() {
  # Une identité *valide* : find-identity -v écarte les certificats expirés ou
  # non fiables. Le nom est ce qu'il y a entre guillemets.
  security find-identity -v -p codesigning 2>/dev/null \
    | grep -o "\"$1[^\"]*\"" | head -1 | tr -d '"'
}

for motif in "Developer ID Application:" "Apple Development:" "$NOM_LOCAL"; do
  nom="$(identite_existante "$motif" || true)"
  if [ -n "$nom" ]; then
    echo "$nom"
    exit 0
  fi
done

echo "   aucune identité de signature : création de « $NOM_LOCAL » (une seule fois)" >&2
ATELIER="$(mktemp -d "${TMPDIR:-/tmp}/greffier-signature.XXXXXX")"
trap 'rm -rf "$ATELIER"' EXIT

# Un certificat de signature de code, auto-signé, dix ans. /usr/bin/openssl
# (LibreSSL) et non un OpenSSL Homebrew : le .p12 qu'il produit est celui que
# `security import` sait lire sans option de compatibilité.
cat > "$ATELIER/extensions.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = $NOM_LOCAL
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
subjectKeyIdentifier = hash
CNF
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout "$ATELIER/cle.pem" -out "$ATELIER/certificat.pem" \
  -config "$ATELIER/extensions.cnf" >/dev/null 2>&1
/usr/bin/openssl pkcs12 -export -inkey "$ATELIER/cle.pem" -in "$ATELIER/certificat.pem" \
  -out "$ATELIER/identite.p12" -passout pass:greffier -name "$NOM_LOCAL" >/dev/null 2>&1

TROUSSEAU="$(security default-keychain -d user | tr -d ' "')"
# -T : codesign peut se servir de la clé sans qu'on le lui autorise à chaque
# signature — sinon un dialogue par bibliothèque signée, il y en a des dizaines.
security import "$ATELIER/identite.p12" -k "$TROUSSEAU" -P greffier \
  -T /usr/bin/codesign -T /usr/bin/security >/dev/null 2>&1 \
  || { echo "⚠️  Import dans le trousseau impossible : signature ad hoc." >&2; echo "-"; exit 0; }
echo "   macOS va demander ton mot de passe pour faire confiance à ce certificat." >&2
if ! security add-trusted-cert -r trustRoot -p codeSign -k "$TROUSSEAU" "$ATELIER/certificat.pem" 2>/dev/null; then
  echo "⚠️  Confiance refusée : signature ad hoc (les autorisations seront redemandées à chaque reconstruction)." >&2
  echo "-"
  exit 0
fi

nom="$(identite_existante "$NOM_LOCAL" || true)"
if [ -n "$nom" ]; then
  echo "$nom"
else
  echo "⚠️  L'identité créée n'est pas utilisable : signature ad hoc." >&2
  echo "-"
fi
