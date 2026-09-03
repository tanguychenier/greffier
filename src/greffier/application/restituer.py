"""Ce qu'on fait d'une réunion une fois qu'elle est transcrite.

Trois restitutions à partir du même fichier maître : le texte envoyé au
rédacteur, un montage des passages marquants avec les vraies voix, et la lecture
du compte rendu à voix haute.

Aucune ne réinvente la transcription : elles partent toutes des horodatages
conservés, ce qui permet de revenir sur une réunion des semaines plus tard.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from greffier.adaptateurs.depot_fichiers import ReunionEnregistree
from greffier.domaine.modeles import Intervalle, Replique, TourDeParole
from greffier.ports import sortants


class Transcrite(Protocol):
    """Ce qu'il faut savoir d'une réunion pour la restituer.

    Un `Protocol` plutôt qu'un type concret : le résultat d'un traitement en
    cours et une réunion relue du disque ont la même forme utile ici, sans
    partager de hiérarchie.
    """

    @property
    def couverture(self) -> float: ...

    @property
    def tours(self) -> list[TourDeParole]: ...

    @property
    def repliques(self) -> list[Replique]: ...

    def trous(self, minimum: float = ...) -> list[Intervalle]: ...
    def temps_de_parole(self) -> dict[str, float]: ...
    def nom_de(self, voix: str | None) -> str: ...

SYSTEME = platform.system()

# En deçà, un trou dans la transcription n'est qu'une respiration.
TROU_SIGNIFICATIF = 8.0
# Sous ce taux, la transcription a manifestement décroché quelque part.
COUVERTURE_SUSPECTE = 0.60


# Les enregistrements sont nommés « 2026-08-25_14h33_sujet ». La date est donc
# sur le disque : sans elle, le rédacteur prend celle du jour du traitement et
# date la réunion de la veille — constaté sur une réunion réelle.
_HORODATAGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:_(\d{2})h(\d{2}))?")

_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre")


def entete_contexte(
    identifiant: str,
    duree: float = 0.0,
    noms: Sequence[str] = (),
    voix_entendues: int = 0,
) -> str:
    """Le contexte de la réunion, dicté au rédacteur mot pour mot.

    Rien n'est deviné : ce qui n'est pas dans le nom du fichier n'est pas écrit.
    Un compte rendu mal daté se retrouve mal classé, et une échéance « jeudi »
    devient fausse d'une semaine.

    La ligne est **composée ici**, pas laissée au rédacteur. Constaté sur deux
    comptes rendus du même jour : l'un annonçait « 2 septembre 2026, 15 h 50,
    durée 2 minutes », l'autre « 2 septembre 2026, 3 min » — sans heure et sans
    participants. Une date et une heure ne sont pas matière à style.

    Quand aucune voix n'a été nommée, on dit **combien** de personnes ont parlé
    plutôt que de taire la question : un compte rendu qui ne dit pas qui était
    là laisse son lecteur sans réponse, et l'absence de nom se corrige d'un clic
    dans l'onglet Voix.
    """
    trouve = _HORODATAGE.match(identifiant)
    lignes = ["[Contexte de la réunion]"]
    contexte = _ligne_de_contexte(trouve, duree, noms, voix_entendues)
    if not contexte:
        return ""
    lignes.append(
        "Reproduis cette ligne telle quelle sous le titre, sans rien y ajouter "
        "ni en retirer :"
    )
    lignes.append(contexte)
    if trouve:
        lignes.append("Emploie cette date, jamais celle du jour.")
    return "\n".join(lignes) + "\n\n"


def _ligne_de_contexte(
    trouve: re.Match[str] | None,
    duree: float,
    noms: Sequence[str],
    voix_entendues: int,
) -> str:
    morceaux: list[str] = []
    if trouve:
        annee, mois, jour, heure, minute = trouve.groups()
        morceaux.append(f"{int(jour)} {_MOIS[int(mois) - 1]} {annee}")
        if heure:
            morceaux.append(_horaires(int(heure), int(minute), duree))
    if duree > 0:
        morceaux.append(f"durée {_duree_lisible(duree)}")
    if not morceaux:
        return ""
    ligne = ", ".join(morceaux) + "."
    presents = _presents(noms, voix_entendues)
    return f"{ligne} {presents}" if presents else ligne


def _horaires(heure: int, minute: int, duree: float) -> str:
    """« de 16 h 46 à 17 h 03 » — l'heure de fin se déduit de la durée."""
    if duree <= 0:
        return f"à {heure} h {minute:02d}"
    fin = (heure * 60 + minute + int(duree // 60)) % (24 * 60)
    return f"de {heure} h {minute:02d} à {fin // 60} h {fin % 60:02d}"


def _presents(noms: Sequence[str], voix_entendues: int) -> str:
    connus = [n for n in dict.fromkeys(noms) if n]
    if connus:
        reste = voix_entendues - len(connus)
        liste = ", ".join(connus)
        if reste > 0:
            pluriel = "s" if reste > 1 else ""
            return f"Participants : {liste}, et {reste} voix non nommée{pluriel}."
        return f"Participants : {liste}."
    if voix_entendues > 0:
        pluriel = "s" if voix_entendues > 1 else ""
        return (f"Participants : {voix_entendues} personne{pluriel} ont parlé, "
                "aucune nommée.")
    return ""


def _duree_lisible(secondes: float) -> str:
    heures, reste = divmod(int(secondes), 3600)
    minutes, restantes = divmod(reste, 60)
    if heures:
        return f"{heures} h {minutes:02d}"
    if minutes:
        return f"{minutes} min"
    # Sous la minute, « 0 min » serait faux : un extrait de trente secondes
    # existe, et le rédacteur doit savoir qu'il n'a qu'un extrait.
    return f"{restantes} s"


def entete_materiel(evenements: list[str]) -> str:
    """Ce que la veille a constaté du matériel, dit au rédacteur.

    Un casque branché après le début veut dire que la voix de la personne qui
    enregistrait manque au commencement. Sans cette ligne, le compte rendu
    présente comme complet un échange dont il n'a entendu qu'un côté.
    """
    if not evenements:
        return ""
    lignes = ["[Matériel audio pendant la réunion]"]
    lignes += [f"- {x}" for x in evenements]
    lignes.append(
        "Ces changements ont coupé la capture en plusieurs morceaux, recollés "
        "ensuite. Les passages enregistrés avant un branchement peuvent ne pas "
        "porter la voix de la personne qui enregistrait : dis-le si un échange "
        "paraît n'avoir qu'un seul côté."
    )
    return "\n".join(lignes) + "\n\n"


def entete_fiabilite(reunion: Transcrite) -> str:
    """Ce que la transcription a perdu, dit au rédacteur avant le texte.

    Sans cela, le compte rendu présente comme complet un texte qui ne l'est pas.
    Mieux vaut un document qui signale ses angles morts qu'un document qui a
    l'air sûr de lui.
    """
    trous = [t for t in reunion.trous(TROU_SIGNIFICATIF) if t.duree >= TROU_SIGNIFICATIF]
    if not trous and reunion.couverture >= COUVERTURE_SUSPECTE:
        return ""

    lignes = ["[Fiabilité de la transcription]"]
    lignes.append(
        f"Couverture : {reunion.couverture * 100:.0f} % de l'audio porte du texte."
    )
    if reunion.couverture < COUVERTURE_SUSPECTE:
        lignes.append(
            "Ce taux est bas : le modèle a probablement décroché sur une partie "
            "de la réunion. Signale-le explicitement dans le compte rendu."
        )
    if trous:
        lignes.append(f"{len(trous)} passage(s) sans aucun texte :")
        for trou in trous[:10]:
            lignes.append(
                f"  {int(trou.debut) // 60:02d}:{int(trou.debut) % 60:02d}"
                f" → {int(trou.fin) // 60:02d}:{int(trou.fin) % 60:02d}"
                f" ({trou.duree:.0f} s)"
            )
        if len(trous) > 10:
            lignes.append(f"  … et {len(trous) - 10} autres")
        lignes.append(
            "Un silence peut être un vrai silence ou du texte perdu : ne comble "
            "aucun de ces passages, contente-toi de les signaler."
        )
    return "\n".join(lignes) + "\n\n"


def rendre_transcription(reunion: Transcrite, entete: str = "") -> str:
    """Transcription lisible, horodatée et attribuée.

    C'est ce texte qui part au rédacteur : les horodatages y restent, pour que
    le compte rendu puisse citer un passage et qu'on puisse y revenir. L'en-tête,
    quand il existe, dit ce que la transcription a perdu — sans lui, le compte
    rendu présenterait comme complet un texte qui ne l'est pas.
    """
    lignes: list[str] = []
    courant: str | None = None
    for replique in reunion.repliques:
        nom = reunion.nom_de(replique.voix)
        if nom != courant:
            lignes.append(f"\n[{nom}]")
            courant = nom
        debut = int(replique.intervalle.debut)
        lignes.append(f"{debut // 60:02d}:{debut % 60:02d}  {replique.texte}")
    return entete + "\n".join(lignes).strip() + "\n"


def regenerer_compte_rendu(reunion: ReunionEnregistree, redacteur: sortants.Redacteur) -> str:
    """Rejoue uniquement la rédaction, depuis ce qui est déjà transcrit.

    Nommer une voix ne change ni la segmentation ni la transcription : rejouer
    toute la chaîne pour ça gâche des minutes de calcul et de modèle. Ce que le
    rédacteur doit refaire, c'est relire le même texte, avec les bonnes étiquettes.
    """
    duree = reunion.tours[-1].intervalle.fin if reunion.tours else 0.0
    entete = (
        entete_contexte(reunion.identifiant, duree)
        + entete_materiel(reunion.evenements_materiel)
        + entete_fiabilite(reunion)
    )
    return redacteur.rediger(rendre_transcription(reunion, entete))


def passages_marquants(
    reunion: Transcrite,
    duree_visee: float = 300.0,
    duree_minimale: float = 8.0,
) -> list[Intervalle]:
    """Les passages à monter bout à bout pour réécouter l'essentiel.

    On prend les plus longs tours de parole, **en répartissant entre les voix
    proportionnellement à leur temps de parole** : un montage qui ne ferait
    entendre que la personne la plus bavarde ne restituerait pas la réunion.
    """
    temps = reunion.temps_de_parole()
    total = sum(temps.values()) or 1.0
    retenus: list[Intervalle] = []

    for voix, parle in temps.items():
        quota = duree_visee * (parle / total)
        if quota < duree_minimale:
            continue
        candidats = sorted(
            (t.intervalle for t in reunion.tours if t.voix == voix),
            key=lambda i: -i.duree,
        )
        cumul = 0.0
        for intervalle in candidats:
            if cumul >= quota:
                break
            if intervalle.duree < duree_minimale:
                continue
            # Un tour très long est tronqué : on veut un échantillon, pas la
            # réunion entière.
            fin = min(intervalle.fin, intervalle.debut + max(duree_minimale, quota - cumul))
            retenus.append(Intervalle(intervalle.debut, fin))
            cumul += fin - intervalle.debut

    # Remis dans l'ordre chronologique : un montage qui saute dans le temps est
    # incompréhensible.
    return sorted(retenus, key=lambda i: i.debut)


def monter(audio: Path, passages: list[Intervalle], destination: Path) -> Path:
    """Découpe et recolle les passages en un seul fichier.

    Ce sont les **vraies voix**, jamais une synthèse : un compte rendu audio ne
    doit pas faire dire à quelqu'un ce qu'il n'a pas prononcé.
    """
    if not passages:
        raise ValueError("aucun passage à monter")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as travail:
        dossier = Path(travail)
        morceaux = []
        for numero, passage in enumerate(passages):
            morceau = dossier / f"{numero:03d}.wav"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{passage.debut:.3f}", "-t", f"{passage.duree:.3f}",
                 "-i", str(audio), "-c:a", "pcm_s16le", str(morceau)],
                check=True,
            )
            morceaux.append(morceau)
        liste = dossier / "liste.txt"
        liste.write_text(
            "\n".join(f"file '{m}'" for m in morceaux) + "\n", encoding="utf-8"
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(liste), "-c:a", "aac", "-b:a", "96k",
             str(destination)],
            check=True,
        )
    return destination


def lire_a_voix_haute(texte: str, destination: Path) -> Path:
    """Enregistre le compte rendu lu par la synthèse du système.

    Pour l'écouter en voiture. Aucune installation : chaque système a déjà de
    quoi lire un texte.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Le Markdown se lit mal à voix haute : on retire ce qui n'est que mise en forme.
    propre = _sans_balisage(texte)

    if SYSTEME == "Darwin":
        with tempfile.TemporaryDirectory() as travail:
            brut = Path(travail) / "lecture.aiff"
            subprocess.run(["say", "-v", "Thomas", "-o", str(brut), propre], check=True)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
                 "-c:a", "aac", "-b:a", "96k", str(destination)],
                check=True,
            )
        return destination
    if shutil.which("espeak-ng"):
        subprocess.run(
            ["espeak-ng", "-v", "fr", "-w", str(destination.with_suffix(".wav")), propre],
            check=True,
        )
        return destination.with_suffix(".wav")
    raise RuntimeError(
        "Aucune synthèse vocale disponible. Sur Linux : « apt install espeak-ng »."
    )


def _sans_balisage(texte: str) -> str:
    """Débarrasse le Markdown de ce qui ne se prononce pas."""
    import re

    propre = re.sub(r"^\s*\|.*\|\s*$", "", texte, flags=re.MULTILINE)  # tableaux
    propre = re.sub(r"[*_`#>]+", "", propre)
    propre = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", propre)           # liens
    propre = re.sub(r"\n{3,}", "\n\n", propre)
    return propre.strip()


def archiver(audio: Path, garder_original: bool = False) -> Path:
    """Compresse un enregistrement traité.

    Un WAV de réunion pèse 115 Mo par heure ; en Opus, une dizaine. La
    transcription est faite, l'audio ne sert plus qu'à réécouter un passage ou
    à réenrôler une voix — la qualité d'un codec vocal suffit largement.
    """
    if audio.suffix == ".opus":
        return audio
    destination = audio.with_suffix(".opus")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
         "-c:a", "libopus", "-b:a", "24k", "-application", "voip", str(destination)],
        check=True,
    )
    if not garder_original:
        audio.unlink()
    return destination
