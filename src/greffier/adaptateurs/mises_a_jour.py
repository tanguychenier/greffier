"""Demander à GitHub s'il existe une version postérieure à celle installée.

Le seul appel réseau de l'outil en dehors de la rédaction, et il est
facultatif : rien ne dépend de lui, une panne de réseau ne coûte que
l'information. Il vise l'API publique des releases, sans jeton — le dépôt est
public, et demander une authentification pour savoir s'il existe une mise à
jour serait absurde.

Ce module ne décide de rien : il rapporte ce que le service répond, et la
comparaison appartient au domaine. Il n'installe rien non plus : remplacer une
application pendant qu'elle tourne est un problème distinct, qui mérite d'être
traité séparément et non en effet de bord d'une vérification.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as version_du_paquet

from greffier.domaine.version import plus_recente

#: Le dépôt public. Configurable par variable d'environnement pour qui
#: travaillerait sur un miroir, sans quoi il faudrait modifier le code.
DEPOT = "tanguychenier/greffier"

#: Court exprès : on ne fait pas attendre une fenêtre pour une information
#: facultative. Cinq secondes suffisent à une réponse de quelques kilooctets.
DELAI = 5.0


@dataclass(frozen=True, slots=True)
class Verdict:
    """Ce que la vérification a appris. `souci` renseigné, rien n'est sûr."""

    installee: str
    disponible: str = ""
    #: L'adresse où la trouver, pour qui veut voir avant d'installer.
    adresse: str = ""
    souci: str = ""

    @property
    def a_jour(self) -> bool:
        return not self.souci and not self.disponible

    @property
    def mise_a_jour(self) -> bool:
        return bool(self.disponible)

    def dire(self) -> str:
        """Une phrase pour l'écran, en français, sans jargon."""
        if self.souci:
            return f"Vérification impossible : {self.souci}"
        if self.disponible:
            return f"Version {self.disponible} disponible (vous avez {self.installee})."
        return f"À jour : version {self.installee}."


def version_installee() -> str:
    """La version du paquet en place, ou une chaîne vide si elle est illisible.

    Lue depuis les métadonnées du paquet plutôt qu'écrite en dur : deux
    endroits qui portent un numéro finissent par se contredire, et c'est
    justement ce qu'on cherche à comparer.
    """
    try:
        return version_du_paquet("greffier")
    except PackageNotFoundError:
        return ""


def verifier(depot: str = DEPOT, delai: float = DELAI) -> Verdict:
    """Interroge la dernière release publiée. Ne lève jamais.

    Une vérification de mise à jour qui fait tomber la fenêtre serait un très
    mauvais échange : tout ce qui peut échouer est rapporté dans `souci`.
    """
    installee = version_installee()
    if not installee:
        return Verdict(installee="", souci="version installée inconnue")

    adresse = f"https://api.github.com/repos/{depot}/releases/latest"
    requete = urllib.request.Request(
        adresse,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Greffier"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            contenu = json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as souci:
        if souci.code == 404:
            # Aucune release publiée : ce n'est pas une panne, c'est un état.
            return Verdict(installee=installee, souci="aucune version publiée")
        return Verdict(installee=installee, souci=f"réponse {souci.code} de GitHub")
    except (urllib.error.URLError, TimeoutError):
        return Verdict(installee=installee, souci="pas de réseau")
    except (ValueError, OSError) as souci:
        return Verdict(installee=installee, souci=str(souci))

    if not isinstance(contenu, dict):
        return Verdict(installee=installee, souci="réponse inattendue")
    etiquette = str(contenu.get("tag_name", "")).strip()
    if not etiquette:
        return Verdict(installee=installee, souci="version publiée sans étiquette")
    if not plus_recente(etiquette, installee):
        return Verdict(installee=installee)
    return Verdict(
        installee=installee,
        disponible=etiquette.lstrip("v"),
        adresse=str(contenu.get("html_url", "")),
    )
