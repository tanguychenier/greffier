"""Écrit `config.toml`, ce que rien ne savait faire jusqu'ici.

La configuration était lue de trois sources et modifiable seulement à la main,
ou par l'assistant qui écrivait un `.env`. Régler le micro ou le rédacteur
depuis la fenêtre demande de savoir **écrire**, et d'écrire au même endroit que
celui d'où on lit — deux fichiers qui se contredisent valent moins que pas de
fichier du tout.

Le fichier est **régénéré**, pas rustiné : les commentaires sont réécrits à
partir de ce module, donc ils ne mentent jamais sur ce que vaut le réglage
voisin. Ce que l'utilisateur avait écrit lui-même dans le fichier est conservé
dans une sauvegarde `config.toml.precedent`, jamais silencieusement perdu.

Seuls les réglages que l'interface propose passent ici. Les chemins, le
vocabulaire et les mots qui ne sont pas des prénoms restent au fichier : ce sont
des listes qui se tiennent mieux dans un éditeur que dans un formulaire, et les
écrire depuis la fenêtre reviendrait à les tronquer.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from greffier.config import Config
from greffier.emplacements import dossier_config

#: Ce qui est écrit, section par section, dans cet ordre. **Tout** ce que la
#: configuration porte de significatif y figure, pas seulement ce que la fenêtre
#: règle : le fichier est régénéré, donc un champ absent d'ici serait perdu — le
#: vocabulaire d'une équipe, par exemple, qui se compte en dizaines de mots et
#: dont la perte dégraderait chaque transcription suivante sans rien annoncer.
#:
#: `chemins` en est délibérément absent. L'y écrire figerait les dossiers dans
#: le fichier : c'est ce que faisait la version précédente, et un poste dont les
#: données ont déménagé continuait de lire l'ancien emplacement.
SECTIONS: dict[str, tuple[str, ...]] = {
    "audio": ("micro", "entree", "sortie", "duree_maximale"),
    "transcription": ("moteur", "modele", "langue", "vocabulaire"),
    "direct": ("actif", "periode", "modele"),
    "locuteurs": ("pas_des_prenoms", "personnes"),
    "compte_rendu": ("moteur", "modele", "destinataire"),
    "courriel": ("serveur", "port", "utilisateur", "expediteur"),
    "apparence": ("theme",),
}

_COMMENTAIRES = {
    "audio": "Périphériques de capture. « micro » vide : le mieux entendu au démarrage.",
    "transcription": ("Le modèle de la transcription définitive, faite après la réunion.\n"
                      "# « vocabulaire » est ce qui améliore le plus les noms propres rares."),
    "direct": "Ce qui s'affiche pendant la réunion. Un second modèle tourne : c'est son coût.",
    "locuteurs": "Mots à ne jamais prendre pour des prénoms : projets, outils, produits.",
    "compte_rendu": ("Qui rédige, avec quel modèle, et à qui le compte rendu part.\n"
                     "# « modele » vide : le second de la gamme, qui suffit pour une synthèse."),
    "courriel": "Envoi SMTP, pour les postes sans Outlook. Le mot de passe n'est jamais ici.",
    "apparence": "systeme suit le réglage clair/sombre du poste.",
}

_ENTETE = """# Configuration de Greffier.
#
# Écrit par l'onglet Réglages de la fenêtre ; modifiable à la main sans risque.
# Tout est facultatif : ce qui manque reprend la valeur par défaut. Les
# variables « GREFFIER_* » et un fichier « .env » l'emportent sur ce fichier,
# dans cet ordre — on doit pouvoir forcer un réglage le temps d'une commande.
#
# La version précédente de ce fichier est conservée en « config.toml.precedent ».
"""


def fichier_config(dossier: Path | None = None) -> Path:
    return (dossier or dossier_config()) / "config.toml"


def rendre(config: Config) -> str:
    """Le contenu TOML de cette configuration. Fonction pure, éprouvable seule."""
    morceaux = [_ENTETE]
    for section, champs in SECTIONS.items():
        modele = getattr(config, section)
        lignes = []
        if section in _COMMENTAIRES:
            lignes.append(f"# {_COMMENTAIRES[section]}")
        lignes.append(f"[{section}]")
        for champ in champs:
            valeur = getattr(modele, champ)
            # TOML n'a pas de « null » : un champ non renseigné s'omet, et la
            # valeur par défaut reprend la main à la lecture.
            if valeur is None:
                continue
            lignes.append(f"{champ} = {_valeur(valeur)}")
        morceaux.append("\n".join(lignes))
    return "\n\n".join(morceaux) + "\n"


def _valeur(valeur: object) -> str:
    """Un scalaire ou une liste, en TOML.

    Pas de `json.dumps` : il rendrait bien `True` en `true` par chance, mais
    aussi les chemins en objets et les caractères accentués en séquences
    d'échappement, là où TOML attend de l'UTF-8 tel quel.
    """
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    if isinstance(valeur, (int, float)):
        return repr(valeur)
    if isinstance(valeur, (list, tuple)):
        if not valeur:
            return "[]"
        return "[" + ", ".join(_valeur(v) for v in valeur) + "]"
    texte = str(valeur).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{texte}"'


def sauver(config: Config, dossier: Path | None = None) -> Path:
    """Écrit la configuration, en gardant une copie de la précédente.

    Écriture atomique : un remplacement, jamais un fichier tronqué. La fenêtre
    enregistre pendant qu'une réunion peut tourner, et un processus auxiliaire
    qui relirait un fichier à moitié écrit s'arrêterait sur une erreur de
    syntaxe.
    """
    cible = fichier_config(dossier)
    cible.parent.mkdir(parents=True, exist_ok=True)
    if cible.exists():
        shutil.copy2(cible, cible.with_suffix(".toml.precedent"))
    # Le fichier temporaire naît dans le dossier de destination : un
    # remplacement n'est atomique que sur le même système de fichiers.
    descripteur, provisoire = tempfile.mkstemp(dir=cible.parent, prefix=".config-",
                                               suffix=".toml")
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as flux:
            flux.write(rendre(config))
        os.replace(provisoire, cible)
    except BaseException:
        Path(provisoire).unlink(missing_ok=True)
        raise
    return cible
